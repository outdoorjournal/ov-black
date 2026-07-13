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
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Itinerary,
    Node,
    Payment,
)
from app.services import node_cost
from app.services.fx import FxService
from app.services.itineraries import ActorContext, ItineraryError, ItineraryOutcome

logger = logging.getLogger("ov_black.invoices")

_ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")

# A node may be billed across several charge lines (a deposit now, the balance
# later — D-PAY amount-aware coverage), but the signed charge total for one node
# must never exceed its effective cost. A cent of slack absorbs client-side
# rounding when a "bill the remaining balance" line is posted as an explicit
# amount, so the exact close-out never trips the guard.
_OVERBILL_TOLERANCE = Decimal("0.01")

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
    """An invoice with its ledger lines, payments, and per-currency subtotals.

    Since 0050 a single invoice may hold lines in several NATIVE currencies, so
    ``subtotals`` (currency → Σ signed line amounts, reversals netting out) is the
    authoritative money shape. ``total`` is retained as a convenience — the sum of
    every line regardless of currency — and is only meaningful for a single-currency
    invoice; multi-currency consumers must read ``subtotals``.
    """

    invoice: Invoice
    lines: list[InvoiceLineItem]
    total: Decimal
    payments: list[Payment]
    subtotals: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class SettlementDisplay:
    """The read-side conversion of an invoice's native subtotals into the single
    currency the traveler pays in (0050). DISPLAY only — the long-cached website
    rate, re-adjusting over time; the actual charge locks a fresher rate at pay
    time (Phase 5, payment_quotes). ``None`` when there is no settlement currency
    or FX is unavailable (then the UI shows native subtotals only)."""

    currency: str
    total: Decimal
    rates: dict[str, Decimal]
    as_of: datetime | None


async def settlement_display(view: InvoiceView, fx: FxService) -> SettlementDisplay | None:
    """Convert ``view.subtotals`` into the invoice's ``settlement_currency``.

    Returns ``None`` when the invoice has no settlement currency, FX is disabled, or
    any needed rate can't be resolved (partial conversions would mislead, so it is
    all-or-nothing). Zero-net currencies are skipped.
    """
    target = view.invoice.settlement_currency
    if target is None or not fx.enabled:
        return None
    rates: dict[str, Decimal] = {}
    total = _ZERO
    as_of: datetime | None = None
    for currency, subtotal in view.subtotals.items():
        if subtotal == _ZERO:
            continue
        rate = await fx.get_rate(currency, target)
        if rate is None:
            return None
        rates[currency] = rate
        total += subtotal * rate
        fetched = fx.fetched_at(currency)
        if fetched is not None and (as_of is None or fetched < as_of):
            as_of = fetched
    return SettlementDisplay(
        currency=target,
        total=total.quantize(_CENTS),
        rates=rates,
        as_of=as_of,
    )


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


async def _node_charged_total(session: AsyncSession, node_id: uuid.UUID) -> Decimal:
    """Σ signed ``charge`` amounts already billed for a node, across EVERY non-void
    invoice, excluding charge lines a ``reversal`` has cancelled.

    This is the coverage base a node's remaining balance is measured against: a
    deposit line on one invoice and the balance line on another both count, so the
    over-billing guard sees the node's whole billed-so-far — not just this
    invoice's slice. Void invoices and reversed charges drop out (they no longer
    cover), mirroring the web ``coverageByNode`` derivation exactly.
    """
    reversed_ids = (
        select(InvoiceLineItem.reverses_line_item_id)
        .where(InvoiceLineItem.reverses_line_item_id.isnot(None))
        .scalar_subquery()
    )
    total = (
        await session.execute(
            select(func.coalesce(func.sum(InvoiceLineItem.amount), _ZERO))
            .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
            .where(
                InvoiceLineItem.node_id == node_id,
                InvoiceLineItem.kind == InvoiceLineKind.charge,
                Invoice.status != InvoiceStatus.void,
                InvoiceLineItem.id.notin_(reversed_ids),
            )
        )
    ).scalar_one()
    return Decimal(total)


def _total_of(lines: list[InvoiceLineItem]) -> Decimal:
    """Σ of signed line amounts, computed in Python from already-fetched rows.

    Only meaningful single-currency (a multi-currency Σ mixes units); prefer
    :func:`subtotals_by_currency` for a multi-currency invoice.
    """
    total = _ZERO
    for line in lines:
        total += line.amount
    return total


def subtotals_by_currency(lines: list[InvoiceLineItem]) -> dict[str, Decimal]:
    """currency → Σ signed line amounts in that currency (reversals net out).

    The authoritative money shape of a (possibly multi-currency) invoice since
    0050. Zero-net currencies are kept so a fully-reversed currency still shows.
    """
    out: dict[str, Decimal] = {}
    for line in lines:
        out[line.currency] = out.get(line.currency, _ZERO) + line.amount
    return out


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
    return InvoiceView(
        invoice=invoice,
        lines=lines,
        total=_total_of(lines),
        payments=payments,
        subtotals=subtotals_by_currency(lines),
    )


async def _client_preferred_currency(session: AsyncSession, itinerary: Itinerary) -> str | None:
    """The owning client's ISO 4217 preferred (settlement) currency, if set."""
    if itinerary.client_id is None:
        return None
    pref = (
        await session.execute(
            select(Client.preferred_currency).where(Client.id == itinerary.client_id)
        )
    ).scalar_one_or_none()
    return pref.strip().upper() if pref else None


@dataclass(frozen=True, slots=True)
class PayContext:
    """Trip + owning-client context for the traveler pay page (I2)."""

    itinerary_title: str
    full_name: str | None
    address: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    preferred_currency: str | None


async def pay_context(
    session: AsyncSession, itinerary_id: uuid.UUID
) -> PayContext | ItineraryError:
    """Load the trip title + owning client's billing identity for the pay page.

    Returns ``NOT_FOUND`` if the itinerary is gone. Client fields are ``None`` when
    the trip has no linked client or the field was never recorded."""
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        return _not_found()
    client: Client | None = None
    if itinerary.client_id is not None:
        client = (
            await session.execute(select(Client).where(Client.id == itinerary.client_id))
        ).scalar_one_or_none()
    return PayContext(
        itinerary_title=itinerary.title,
        full_name=client.full_name if client else None,
        address=client.address if client else None,
        city=client.city if client else None,
        region=client.region if client else None,
        postal_code=client.postal_code if client else None,
        country_code=client.country_code if client else None,
        preferred_currency=client.preferred_currency if client else None,
    )


async def create_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    label: str,
    currency: str,
    due_at: datetime | None = None,
    settlement_currency: str | None = None,
) -> Invoice | ItineraryError:
    """Create a draft invoice over an existing itinerary.

    ``settlement_currency`` (the single currency the traveler pays in) defaults to
    the owning client's ``preferred_currency``; pass it explicitly to override. NULL
    when neither is set → the invoice is paid in its native currency (back-compat).
    """
    currency = currency.strip().upper()
    if not currency:
        return _err("currency_required")
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        return _not_found()

    settlement = (settlement_currency or "").strip().upper() or None
    if settlement is None:
        settlement = await _client_preferred_currency(session, itinerary)

    invoice = Invoice(
        itinerary_id=itinerary_id,
        label=label,
        currency=currency,
        settlement_currency=settlement,
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
    if len(currency) != 3 or not currency.isalpha():
        return _err("currency_invalid")

    if node_id is not None:
        node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
        if node is None or node.itinerary_id != invoice.itinerary_id:
            return _err("node_not_in_itinerary")
        # A node line must carry the node's NATIVE currency (0050): one invoice may
        # hold several currencies, but a given node's charge is only ever native so
        # the money gate's per-node native coverage stays exact.
        if node.cost_currency is not None and currency != node.cost_currency.upper():
            return _err("currency_mismatch")
        # Amount-aware coverage (D-PAY): a node may be split across a deposit +
        # balance, but its running charge total can't exceed its effective cost —
        # else per-node coverage would over-count. Guards ``charge`` lines only (a
        # node-tagged discount is a correction, not coverage) and only when the
        # node carries a cost to measure against.
        if kind is InvoiceLineKind.charge and node.cost_amount is not None:
            party_size = await node_cost.resolve_party_size(session, invoice.itinerary_id)
            effective = node_cost.effective_node_cost(node.cost_amount, node.cost_kind, party_size)
            already = await _node_charged_total(session, node_id)
            if already + amount > effective + _OVERBILL_TOLERANCE:
                return _err("node_overbilled")

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
    from the node title. A ``per_person`` cost is expanded by the itinerary's
    party size (:func:`node_cost.effective_node_cost`) so the charged line matches
    the amount the money gate books and reconciles for the same node.
    """
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None:
        return _not_found()
    node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
    if node is None or node.itinerary_id != invoice.itinerary_id:
        return _err("node_not_in_itinerary")
    if node.cost_amount is None or node.cost_currency is None:
        return _err("node_has_no_cost")

    party_size = await node_cost.resolve_party_size(session, invoice.itinerary_id)
    amount = node_cost.effective_node_cost(node.cost_amount, node.cost_kind, party_size)
    return await add_line_item(
        session,
        actor,
        invoice_id=invoice_id,
        description=node.title or "",
        amount=amount,
        currency=node.cost_currency,
        kind=InvoiceLineKind.charge,
        node_id=node_id,
    )


def build_reversal_line(
    actor: ActorContext,
    *,
    original: InvoiceLineItem,
    description: str | None = None,
) -> InvoiceLineItem:
    """Construct (without adding/committing) a ``reversal`` line negating ``original``.

    Shared by :func:`void_line_item` (an advisor's append-only void on an open
    invoice) and the booking-cancel refund path (which reverses a charge on an
    already-*paid* invoice) so the journal-entry shape stays identical; only the
    paid-invoice guard differs between the two callers.
    """
    return InvoiceLineItem(
        invoice_id=original.invoice_id,
        node_id=original.node_id,
        kind=InvoiceLineKind.reversal,
        description=(description or f"Reversal of: {original.description}").strip(),
        amount=-original.amount,
        currency=original.currency,
        reverses_line_item_id=original.id,
        created_by=actor.user_id,
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

    reversal = build_reversal_line(actor, original=original)
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
    invoice.issued_at = datetime.now(UTC)
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


async def mark_invoice_viewed(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
) -> None:
    """Stamp ``first_viewed_at`` the first time the owning traveler opens the
    invoice (advisor signal, 0050). Idempotent — a no-op once already set. Best
    effort: a failure here must never block the read, so callers ignore errors."""
    invoice = await _load_invoice(session, invoice_id)
    if invoice is None or invoice.first_viewed_at is not None:
        return
    invoice.first_viewed_at = datetime.now(UTC)
    await session.commit()
    logger.info("invoice.viewed", extra={"invoice_id": str(invoice_id)})


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
            subtotals=subtotals_by_currency(lines_by_invoice.get(inv.id, [])),
        )
        for inv in invoices
    ]


async def list_invoices_for_client(
    session: AsyncSession,
    client_id: uuid.UUID,
) -> list[tuple[InvoiceView, Itinerary]]:
    """Every invoice across the client's itineraries, each paired with its itinerary.

    Newest first. Batches the ledger + payments like :func:`list_invoices` so each
    ``total`` is the real Σ(lines) without an N+1. Powers the traveler's
    cross-trip ``GET /me/invoices`` listing.
    """
    rows = list(
        (
            await session.execute(
                select(Invoice, Itinerary)
                .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
                .where(Itinerary.client_id == client_id)
                .order_by(Invoice.created_at.desc(), Invoice.id)
            )
        ).all()
    )
    if not rows:
        return []
    invoice_ids = [inv.id for inv, _ in rows]
    lines_by_invoice = await _lines_for_many(session, invoice_ids)
    payments_by_invoice = await _payments_for_many(session, invoice_ids)
    return [
        (
            InvoiceView(
                invoice=inv,
                lines=lines_by_invoice.get(inv.id, []),
                total=_total_of(lines_by_invoice.get(inv.id, [])),
                payments=payments_by_invoice.get(inv.id, []),
                subtotals=subtotals_by_currency(lines_by_invoice.get(inv.id, [])),
            ),
            itin,
        )
        for inv, itin in rows
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
