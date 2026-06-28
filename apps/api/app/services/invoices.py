"""Invoice assembly + line-item ledger (M005 / I1).

An advisor assembles one or more invoices over an itinerary's approved bookable
nodes. Each invoice is a small LEDGER: line items are *signed* entries — charges
(usually derived from a node's B4 cost), discounts and child/elderly adjustments
(negative), taxes/fees, and append-only ``reversal`` voids. The invoice total is
always ``Σ(line amounts)``; there is no stored total, so the ledger is the single
source of truth the money gate (I3) reconciles against (mvp-plan §5).

This module reuses the :class:`ActorContext` / :class:`ItineraryError` /
:class:`ItineraryOutcome` envelope from :mod:`app.services.itineraries` (like
:mod:`app.services.fork`) so the HTTP layer maps outcomes with one helper.

Lifecycle gates:
- ``draft`` — freely editable (charges assembled here; lines hard-deletable).
- ``issued`` — append-only: *adjusting* lines (discount/adjustment/tax/fee/
  reversal) are allowed so corrections stay journal entries, but a new ``charge``
  or a hard delete is refused (demote semantics live in the draft phase).
- ``paid`` / ``void`` — closed: no line mutations.

``mark_invoice_paid`` is defined here but driven by I2 (payments) on a settled
sale.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Itinerary,
    Node,
    Payment,
)
from app.services.itineraries import ActorContext, ItineraryError, ItineraryOutcome

logger = logging.getLogger("ov_black.invoices")

_ZERO = Decimal("0.00")

# Kinds an *issued* (append-only) invoice still accepts — corrections that read
# as journal entries. A fresh ``charge`` must be assembled while the invoice is
# still a draft.
_ADJUSTING_KINDS = frozenset(
    {
        InvoiceLineKind.discount,
        InvoiceLineKind.adjustment,
        InvoiceLineKind.tax,
        InvoiceLineKind.fee,
        InvoiceLineKind.reversal,
    }
)


@dataclass(frozen=True, slots=True)
class InvoiceView:
    """An invoice with its ledger lines, payments, and computed total (Σ lines)."""

    invoice: Invoice
    lines: list[InvoiceLineItem]
    total: Decimal
    payments: list[Payment]


def _err(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail=detail)


def _not_found() -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)


async def _load_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> Invoice | None:
    return (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one_or_none()


async def _invoice_total(session: AsyncSession, invoice_id: uuid.UUID) -> Decimal:
    """Σ of every line's signed ``amount`` (reversal pairs net to zero).

    Standalone SUM for callers that haven't already fetched the lines (e.g. the
    pay path totals an invoice without materializing the ledger). When the lines
    are already in hand, use :func:`_total_of` instead of a second round-trip.
    """
    total = (
        await session.execute(
            select(func.coalesce(func.sum(InvoiceLineItem.amount), _ZERO)).where(
                InvoiceLineItem.invoice_id == invoice_id
            )
        )
    ).scalar_one()
    return Decimal(total)


def _total_of(lines: list[InvoiceLineItem]) -> Decimal:
    """Σ of signed line amounts, computed in Python from already-fetched rows."""
    total = _ZERO
    for line in lines:
        total += line.amount
    return total


async def _lines_for(session: AsyncSession, invoice_id: uuid.UUID) -> list[InvoiceLineItem]:
    return list(
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.created_at, InvoiceLineItem.id)
            )
        )
        .scalars()
        .all()
    )


async def _payments_for(session: AsyncSession, invoice_id: uuid.UUID) -> list[Payment]:
    return list(
        (
            await session.execute(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.created_at, Payment.id)
            )
        )
        .scalars()
        .all()
    )


async def _lines_for_many(
    session: AsyncSession, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[InvoiceLineItem]]:
    """All line items for several invoices in ONE query, grouped by invoice id."""
    rows = (
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id.in_(invoice_ids))
                .order_by(InvoiceLineItem.created_at, InvoiceLineItem.id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[InvoiceLineItem]] = {}
    for row in rows:
        grouped.setdefault(row.invoice_id, []).append(row)
    return grouped


async def _payments_for_many(
    session: AsyncSession, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Payment]]:
    """All payments for several invoices in ONE query, grouped by invoice id."""
    rows = (
        (
            await session.execute(
                select(Payment)
                .where(Payment.invoice_id.in_(invoice_ids))
                .order_by(Payment.created_at, Payment.id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[Payment]] = {}
    for row in rows:
        grouped.setdefault(row.invoice_id, []).append(row)
    return grouped


async def _view(session: AsyncSession, invoice: Invoice) -> InvoiceView:
    # Two round-trips, not three: the total is Σ(lines) we already fetched, so a
    # separate SUM query would re-read the same rows.
    lines = await _lines_for(session, invoice.id)
    payments = await _payments_for(session, invoice.id)
    return InvoiceView(invoice=invoice, lines=lines, total=_total_of(lines), payments=payments)


async def create_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    label: str,
    currency: str,
    due_at: datetime | None = None,
) -> Invoice | ItineraryError:
    """Create a draft invoice over an existing itinerary."""
    currency = currency.strip().upper()
    if not currency:
        return _err("currency_required")
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        return _not_found()

    invoice = Invoice(
        itinerary_id=itinerary_id,
        label=label,
        currency=currency,
        status=InvoiceStatus.draft,
        due_at=due_at,
        created_by=actor.user_id,
    )
    session.add(invoice)
    await session.flush()
    await session.commit()
    logger.info(
        "invoice.create",
        extra={
            "invoice_id": str(invoice.id),
            "itinerary_id": str(itinerary_id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return invoice


async def add_line_item(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
    description: str,
    amount: Decimal,
    currency: str,
    kind: InvoiceLineKind = InvoiceLineKind.charge,
    node_id: uuid.UUID | None = None,
) -> InvoiceLineItem | ItineraryError:
    """Append a signed line. ``draft`` accepts any kind; ``issued`` accepts only
    adjusting kinds; ``paid``/``void`` accept none."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()

    gate = _gate_line_write(invoice.status, kind)
    if gate is not None:
        return gate

    if amount == _ZERO:
        return _err("zero_amount")

    currency = currency.strip().upper()
    if currency != invoice.currency:
        return _err("currency_mismatch")

    if node_id is not None:
        node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
        if node is None or node.itinerary_id != invoice.itinerary_id:
            return _err("node_not_in_itinerary")

    line = InvoiceLineItem(
        invoice_id=invoice_id,
        node_id=node_id,
        kind=kind,
        description=description,
        amount=amount,
        currency=currency,
        created_by=actor.user_id,
    )
    session.add(line)
    await session.flush()
    await session.commit()
    logger.info(
        "invoice.line.add",
        extra={
            "invoice_id": str(invoice_id),
            "line_id": str(line.id),
            "kind": kind.value,
            "actor_kind": actor.kind.value,
        },
    )
    return line


async def add_line_item_from_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
    node_id: uuid.UUID,
) -> InvoiceLineItem | ItineraryError:
    """Convenience: derive a ``charge`` line from a node's B4 cost.

    Amount/currency come from ``cost_amount``/``cost_currency``; the description
    from the node title. Per-person amounts are billed at face value (party-size
    expansion is the I3 money-gate concern).
    """
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
    if node is None or node.itinerary_id != invoice.itinerary_id:
        return _err("node_not_in_itinerary")
    if node.cost_amount is None or node.cost_currency is None:
        return _err("node_has_no_cost")

    return await add_line_item(
        session,
        actor,
        invoice_id=invoice_id,
        description=node.title or "",
        amount=node.cost_amount,
        currency=node.cost_currency,
        kind=InvoiceLineKind.charge,
        node_id=node_id,
    )


async def void_line_item(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
    line_item_id: uuid.UUID,
) -> InvoiceLineItem | ItineraryError:
    """Void a line by appending a ``reversal`` (amount = -original) — the
    journal-entry void, never a mutation/delete."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.void):
        return _err("invoice_closed")

    original = (
        await session.execute(
            select(InvoiceLineItem).where(
                InvoiceLineItem.id == line_item_id,
                InvoiceLineItem.invoice_id == invoice_id,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        return _err("line_not_found")
    if original.kind is InvoiceLineKind.reversal:
        return _err("cannot_reverse_reversal")

    existing_reversal = (
        await session.execute(
            select(InvoiceLineItem.id).where(InvoiceLineItem.reverses_line_item_id == line_item_id)
        )
    ).scalar_one_or_none()
    if existing_reversal is not None:
        return _err("already_reversed")

    reversal = InvoiceLineItem(
        invoice_id=invoice_id,
        node_id=original.node_id,
        kind=InvoiceLineKind.reversal,
        description=f"Reversal of: {original.description}".strip(),
        amount=-original.amount,
        currency=original.currency,
        reverses_line_item_id=original.id,
        created_by=actor.user_id,
    )
    session.add(reversal)
    await session.flush()
    await session.commit()
    logger.info(
        "invoice.line.void",
        extra={
            "invoice_id": str(invoice_id),
            "reversed_line_id": str(line_item_id),
            "reversal_line_id": str(reversal.id),
            "actor_kind": actor.kind.value,
        },
    )
    return reversal


async def remove_line_item(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
    line_item_id: uuid.UUID,
) -> None | ItineraryError:
    """Hard-delete a line — draft-only (assembly convenience). After issue, use
    :func:`void_line_item`."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    if invoice.status is not InvoiceStatus.draft:
        return _err("invoice_not_draft")
    line = (
        await session.execute(
            select(InvoiceLineItem).where(
                InvoiceLineItem.id == line_item_id,
                InvoiceLineItem.invoice_id == invoice_id,
            )
        )
    ).scalar_one_or_none()
    if line is None:
        return _err("line_not_found")
    await session.delete(line)
    await session.commit()
    logger.info(
        "invoice.line.remove",
        extra={"invoice_id": str(invoice_id), "line_id": str(line_item_id)},
    )
    return None


async def issue_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
) -> Invoice | ItineraryError:
    """Flip ``draft → issued``. Requires at least one line."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    if invoice.status is not InvoiceStatus.draft:
        return _err("invoice_not_draft")
    line_count = (
        await session.execute(
            select(func.count(InvoiceLineItem.id)).where(InvoiceLineItem.invoice_id == invoice_id)
        )
    ).scalar_one()
    if not line_count:
        return _err("no_line_items")

    invoice.status = InvoiceStatus.issued
    await session.commit()
    logger.info(
        "invoice.issue",
        extra={"invoice_id": str(invoice_id), "actor_kind": actor.kind.value},
    )
    return invoice


async def void_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    invoice_id: uuid.UUID,
) -> Invoice | ItineraryError:
    """Cancel an invoice (``draft``/``issued`` → ``void``). A paid invoice
    can't be voided (refund is a future concern)."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    if invoice.status in (InvoiceStatus.paid, InvoiceStatus.void):
        return _err("invoice_closed")
    invoice.status = InvoiceStatus.void
    await session.commit()
    logger.info(
        "invoice.void",
        extra={"invoice_id": str(invoice_id), "actor_kind": actor.kind.value},
    )
    return invoice


async def mark_invoice_paid(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
) -> Invoice | ItineraryError:
    """Flip ``issued → paid`` (driven by I2 on a settled sale). Caller commits."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    if invoice.status is not InvoiceStatus.issued:
        return _err("invoice_not_issued")
    invoice.status = InvoiceStatus.paid
    logger.info("invoice.paid", extra={"invoice_id": str(invoice_id)})
    return invoice


async def get_invoice(
    session: AsyncSession,
    invoice_id: uuid.UUID,
) -> InvoiceView | ItineraryError:
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    return await _view(session, invoice)


async def list_invoices(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
) -> list[InvoiceView]:
    invoices = list(
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.itinerary_id == itinerary_id)
                .order_by(Invoice.created_at, Invoice.id)
            )
        )
        .scalars()
        .all()
    )
    if not invoices:
        return []
    # Batch the ledger + payments for ALL invoices in two queries instead of the
    # 3·N a per-invoice _view() would issue (the old N+1).
    invoice_ids = [inv.id for inv in invoices]
    lines_by_invoice = await _lines_for_many(session, invoice_ids)
    payments_by_invoice = await _payments_for_many(session, invoice_ids)
    return [
        InvoiceView(
            invoice=inv,
            lines=lines_by_invoice.get(inv.id, []),
            total=_total_of(lines_by_invoice.get(inv.id, [])),
            payments=payments_by_invoice.get(inv.id, []),
        )
        for inv in invoices
    ]


def _gate_line_write(status: InvoiceStatus, kind: InvoiceLineKind) -> ItineraryError | None:
    """Reject a line write the invoice's lifecycle forbids."""
    if status is InvoiceStatus.draft:
        return None
    if status is InvoiceStatus.issued:
        if kind in _ADJUSTING_KINDS:
            return None
        # A fresh charge must be assembled while still a draft.
        return _err("invoice_not_draft")
    # paid / void
    return _err("invoice_closed")
