"""Booking workflow + the money gate (M005 / I3).

A node's lifecycle is ``approved → booked → confirmed``. Promotion *into*
``booked`` is the money gate: a node may book only when a covering **paid**
invoice line exists (an advisor may override onto a merely *issued* line, which
is logged). This is the one authorized path to ``booked`` — the graph
``update_node`` path refuses a direct status flip to booked/confirmed so the
gate can't be bypassed.

Two structured tables back it (D024):

- ``node_offers`` — time-boxed, repriceable supplier quotes. A flight is a price
  HELD until ``expires_at``; it MUST be re-priced before booking, so a flight
  node requires a *fresh* offer to book. :func:`refresh_offer` re-prices live
  through the inventory provider (a Duffel ``GET /air/offers/{id}``) where the
  node carries a provider source, else snapshots the node's B4 cost.
- ``bookings`` — the committed record: the amount actually charged (the
  re-priced/held amount), the offer + covering invoice line it links to, the
  supplier confirmation # (set at ``confirmed``), and the logged
  ``override_unpaid`` flag.

The reconciliation invariant (:func:`reconcile_itinerary`) reads both tables
plus the 0023 ledger and checks Σ(paid invoice lines) ⇔ Σ(booked node costs)
per currency, surfacing any per-node delta (booked-but-unpaid, under/over-charge
from a re-price).

This module reuses the :class:`ActorContext` / :class:`ItineraryError` /
:class:`ItineraryOutcome` envelope from :mod:`app.services.itineraries` so the
HTTP layer maps outcomes with one helper and the service never raises.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.inventory.providers.duffel import ProviderUpstreamError
from app.inventory.registry import (
    InventoryCtx,
    InventoryProviderRegistry,
    UnknownSourceError,
    get_registry,
)
from app.inventory.supplier_booking import (
    SupplierAvailability,
    SupplierBookingError,
    SupplierBookingProvider,
    SupplierSelection,
)
from app.models import (
    Booking,
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Node,
    NodeOffer,
    NodeStatus,
    NodeType,
    Payment,
    PaymentStatus,
    RefundStatus,
)
from app.observability import emit_metric, span
from app.payments.base import PaymentGateway, PaymentGatewayError, new_refund_reference
from app.services.invoices import build_reversal_line
from app.services.itineraries import (
    ActorContext,
    ItineraryError,
    ItineraryOutcome,
    _snapshot_node,
    _write_node_history,
)
from app.services.node_cost import (
    cost_from_inventory_item,
    effective_node_cost,
    resolve_party_size,
)

logger = logging.getLogger("ov_black.bookings")

_ZERO = Decimal("0.00")

# A snapshot quote (no live provider behind it) is our own static price; we still
# stamp a freshness window so the flight gate's "needs a fresh offer" check has
# uniform semantics. A live Duffel offer carries its own (shorter) ``expires_at``.
_SNAPSHOT_OFFER_TTL = timedelta(minutes=30)

# Booked-promotion is allowed only from this status.
_BOOKABLE_FROM = NodeStatus.approved
# Statuses a booking covers — the reconciliation invariant sums over these.
_BOOKED_STATUSES: tuple[NodeStatus, ...] = (NodeStatus.booked, NodeStatus.confirmed)


@dataclass(frozen=True, slots=True)
class BookingView:
    """A booking with the node's resulting status and any re-price delta.

    ``reprice_delta`` is ``booked amount − node.cost_amount`` (the B4 snapshot)
    when both are known and differ — the surfaced flight re-price; ``None`` when
    there's nothing to flag.
    """

    booking: Booking
    node_status: NodeStatus
    offer: NodeOffer | None
    reprice_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class ReconciliationRow:
    """Per-currency reconciliation: Σ(paid lines for booked nodes) vs Σ(booked)."""

    currency: str
    paid_total: Decimal
    booked_total: Decimal
    balanced: bool


@dataclass(frozen=True, slots=True)
class ReconciliationViolation:
    """A booked node whose paid coverage doesn't match its booked amount."""

    node_id: uuid.UUID
    code: str  # booked_unpaid | undercharged | overcharged
    currency: str
    booked_amount: Decimal
    paid_amount: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    rows: list[ReconciliationRow]
    violations: list[ReconciliationViolation]
    balanced: bool


@dataclass(frozen=True, slots=True)
class NodeCharges:
    """The money facet for a single node (M006/PS4): its billed charge line, the
    covering invoice's status + id (the pay target), the paid/owed split, and the
    node's live booking. A read-only roll-*down* of the ledger to one inventory
    item — the mirror of the Dashboard roll-*up*; the pay/book actions themselves
    live on the invoice + booking endpoints. Charges add and reversals subtract,
    matching reconciliation; a voided invoice's lines are ignored."""

    node_id: uuid.UUID
    node_status: NodeStatus
    currency: str | None
    line_item_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    invoice_status: InvoiceStatus | None
    billed_amount: Decimal
    paid_amount: Decimal
    owed_amount: Decimal
    booking: Booking | None


def _err(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail=detail)


def _conflict(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.CONFLICT, detail=detail)


def _not_found() -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)


def _now() -> datetime:
    return datetime.now(UTC)


async def _load_node(
    session: AsyncSession, itinerary_id: uuid.UUID, node_id: uuid.UUID
) -> Node | None:
    return (
        await session.execute(
            select(Node).where(Node.id == node_id, Node.itinerary_id == itinerary_id)
        )
    ).scalar_one_or_none()


async def _latest_offer(session: AsyncSession, node_id: uuid.UUID) -> NodeOffer | None:
    return (
        await session.execute(
            select(NodeOffer)
            .where(NodeOffer.node_id == node_id)
            .order_by(NodeOffer.priced_at.desc(), NodeOffer.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _booking_for(session: AsyncSession, node_id: uuid.UUID) -> Booking | None:
    """The node's LIVE booking (cancelled rows are excluded — a cancelled node is
    demoted to ``approved`` and re-bookable, so its old booking no longer counts)."""
    return (
        await session.execute(
            select(Booking).where(
                Booking.node_id == node_id,
                Booking.cancelled_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _covering_invoice_id(session: AsyncSession, line_item_id: uuid.UUID) -> uuid.UUID | None:
    return (
        await session.execute(
            select(InvoiceLineItem.invoice_id).where(InvoiceLineItem.id == line_item_id)
        )
    ).scalar_one_or_none()


async def _latest_succeeded_payment(session: AsyncSession, invoice_id: uuid.UUID) -> Payment | None:
    """The most recent settled gateway charge on an invoice — the refund target."""
    return (
        await session.execute(
            select(Payment)
            .where(
                Payment.invoice_id == invoice_id,
                Payment.status == PaymentStatus.succeeded,
                Payment.processor_transaction_id.isnot(None),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _offer_expired(offer: NodeOffer, *, at: datetime) -> bool:
    """A flight quote is valid only while ``now < expires_at`` (null = no expiry)."""
    return offer.expires_at is not None and offer.expires_at <= at


# ── Offers: re-price (live provider or snapshot) ─────────────────────────────


async def refresh_offer(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    registry: InventoryProviderRegistry | None = None,
) -> NodeOffer | ItineraryError:
    """Attach a fresh quote to a node, re-pricing the held amount.

    When the node carries a provider source (a Duffel flight: ``source='duffel'``
    + ``source_id=<offer id>``) the quote is re-priced LIVE via the provider's
    ``get_detail`` — Duffel's ``GET /air/offers/{id}`` returns the current
    ``total_amount`` + ``expires_at``, or 404s once the held price lapses. With
    no live provider the quote is *snapshotted* from the node's B4 cost with a
    fixed freshness window. Either way a ``node_offers`` row is appended, chained
    to the prior quote via ``refreshed_from_offer_id``.
    """
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()

    prior = await _latest_offer(session, node_id)
    registry = registry or get_registry()

    source: str
    source_offer_id: str | None
    amount: Decimal
    currency: str
    expires_at: datetime | None
    raw: dict[str, object]

    if node.source and node.source_id and node.source in registry.enabled_sources():
        try:
            provider = registry.get(node.source)
            item = await provider.get_detail(
                source_id=node.source_id,
                ctx=InventoryCtx(actor_kind=actor.kind.value, actor_id=actor.actor_id),
            )
        except (ProviderUpstreamError, UnknownSourceError) as exc:
            logger.warning(
                "booking.offer.reprice_failed",
                extra={"node_id": str(node_id), "source": node.source, "reason": str(exc)},
            )
            return _conflict("reprice_failed")
        if item is None:
            # The held offer lapsed (Duffel 404) — it can't be re-priced in place;
            # the advisor must re-search and re-attach a new offer.
            return _conflict("offer_unavailable")
        cost = cost_from_inventory_item(item)
        if cost is None:
            return _err("offer_unpriced")
        source = node.source
        source_offer_id = node.source_id
        amount, currency = cost.amount, cost.currency
        expires_at = _parse_expires_at(item.raw)
        raw = dict(item.raw)
    else:
        # Snapshot fallback — freeze the node's static B4 cost as the quote.
        if node.cost_amount is None or node.cost_currency is None:
            return _err("node_has_no_cost")
        source = "snapshot"
        source_offer_id = None
        amount, currency = node.cost_amount, node.cost_currency
        expires_at = _now() + _SNAPSHOT_OFFER_TTL
        raw = {}

    offer = NodeOffer(
        node_id=node_id,
        source=source,
        source_offer_id=source_offer_id,
        amount=amount,
        currency=currency,
        priced_at=_now(),
        expires_at=expires_at,
        refreshed_from_offer_id=prior.id if prior is not None else None,
        raw=raw,
        created_by=actor.user_id,
    )
    session.add(offer)
    await session.flush()
    await session.commit()
    logger.info(
        "booking.offer.refresh",
        extra={
            "node_id": str(node_id),
            "offer_id": str(offer.id),
            "source": source,
            "repriced_from": str(prior.id) if prior is not None else None,
        },
    )
    return offer


def _parse_expires_at(raw: dict[str, object]) -> datetime | None:
    """Pull a tz-aware ``expires_at`` out of a raw Duffel offer payload."""
    value = raw.get("expires_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def list_offers(session: AsyncSession, node_id: uuid.UUID) -> list[NodeOffer]:
    return list(
        (
            await session.execute(
                select(NodeOffer)
                .where(NodeOffer.node_id == node_id)
                .order_by(NodeOffer.priced_at.desc(), NodeOffer.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


# ── The money gate: approved → booked ────────────────────────────────────────


async def _node_paid_coverage(
    session: AsyncSession,
    node_id: uuid.UUID,
    currency: str,
    *,
    statuses: Sequence[InvoiceStatus],
) -> Decimal:
    """Net signed Σ of this node's invoice lines on invoices in ``statuses``.

    Charges add, reversals subtract — so a voided charge stops covering the node.
    Discounts/fees are normally invoice-level (no ``node_id``) so they don't
    reduce a node's coverage here.
    """
    total = (
        await session.execute(
            select(func.coalesce(func.sum(InvoiceLineItem.amount), _ZERO))
            .select_from(InvoiceLineItem)
            .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
            .where(
                InvoiceLineItem.node_id == node_id,
                InvoiceLineItem.currency == currency,
                Invoice.status.in_(list(statuses)),
            )
        )
    ).scalar_one()
    return Decimal(total)


async def _pick_covering_line(
    session: AsyncSession,
    node_id: uuid.UUID,
    currency: str,
    *,
    statuses: Sequence[InvoiceStatus],
) -> uuid.UUID | None:
    """The most recent ``charge`` line covering the node — the FK we link to."""
    return (
        await session.execute(
            select(InvoiceLineItem.id)
            .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
            .where(
                InvoiceLineItem.node_id == node_id,
                InvoiceLineItem.currency == currency,
                InvoiceLineItem.kind == InvoiceLineKind.charge,
                Invoice.status.in_(list(statuses)),
            )
            .order_by(InvoiceLineItem.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def node_charges(
    session: AsyncSession, itinerary_id: uuid.UUID, node_id: uuid.UUID
) -> NodeCharges | ItineraryError:
    """This node's money facet (M006/PS4).

    Sums the node's invoice lines across its non-void invoices — ``billed`` over
    issued+paid, ``paid`` over paid only, so ``owed = billed − paid``; reversals
    net out (a voided charge stops billing). The ``primary`` line/invoice a pay
    action targets is the most recent ``charge`` line, preferring a payable
    (issued) invoice, then paid, then draft. Also attaches the node's live
    booking (cancelled rows excluded, per :func:`_booking_for`).
    """
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()

    rows = (
        await session.execute(
            select(InvoiceLineItem, Invoice.status, Invoice.id)
            .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
            .where(
                InvoiceLineItem.node_id == node_id,
                Invoice.status != InvoiceStatus.void,
            )
            .order_by(InvoiceLineItem.created_at.asc())
        )
    ).all()

    # A payable invoice outranks a settled one outranks a still-draft one, so the
    # facet's single "pay this" affordance points at the line that can be acted on.
    _rank = {InvoiceStatus.issued: 3, InvoiceStatus.paid: 2, InvoiceStatus.draft: 1}
    billed = _ZERO
    paid = _ZERO
    currency: str | None = None
    primary: tuple[InvoiceLineItem, InvoiceStatus, uuid.UUID] | None = None
    for line, status, invoice_id in rows:
        if currency is None:
            currency = line.currency
        if status in (InvoiceStatus.issued, InvoiceStatus.paid):
            billed += line.amount
        if status is InvoiceStatus.paid:
            paid += line.amount
        if line.kind is InvoiceLineKind.charge and (
            primary is None or _rank.get(status, 0) > _rank.get(primary[1], 0)
        ):
            primary = (line, status, invoice_id)

    booking = await _booking_for(session, node_id)
    return NodeCharges(
        node_id=node_id,
        node_status=node.status,
        currency=currency,
        line_item_id=primary[0].id if primary else None,
        invoice_id=primary[2] if primary else None,
        invoice_status=primary[1] if primary else None,
        billed_amount=billed,
        paid_amount=paid,
        owed_amount=billed - paid,
        booking=booking,
    )


def _supplier_booking_provider(
    settings: Settings,
    node: Node,
    registry: InventoryProviderRegistry,
) -> SupplierBookingProvider | None:
    """The provider that can BOOK this node's source, if the supplier path is on.

    Returns ``None`` (→ the legacy manual flow: book locally, advisor records the
    confirmation # later) unless supplier booking is enabled, the node carries a
    provider source + id, and that provider implements the
    :class:`SupplierBookingProvider` capability.
    """
    if not settings.bokun_booking_enabled:
        return None
    if not (node.source and node.source_id):
        return None
    if node.source not in registry.enabled_sources():
        return None
    provider = registry.get(node.source)
    return provider if isinstance(provider, SupplierBookingProvider) else None


def _supplier_provider_for_booking(
    booking: Booking,
    registry: InventoryProviderRegistry,
) -> SupplierBookingProvider | None:
    """The provider that made ``booking``, for the cancel path.

    Resolved from what was actually booked (``supplier_source`` +
    ``supplier_booking_id``), NOT the enable flag — a booking already placed
    upstream must be cancelled upstream even if new supplier bookings were since
    turned off. ``None`` when the booking has no supplier leg.
    """
    source = booking.supplier_source
    if not source or not booking.supplier_booking_id:
        return None
    if source not in registry.enabled_sources():
        return None
    provider = registry.get(source)
    return provider if isinstance(provider, SupplierBookingProvider) else None


async def list_supplier_availability(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    start: date,
    end: date,
    currency: str = "USD",
    registry: InventoryProviderRegistry | None = None,
    settings: Settings | None = None,
) -> list[SupplierAvailability] | ItineraryError:
    """List a supplier-bookable node's real availability over ``[start, end]``.

    The slots feed a :class:`SupplierSelection` for :func:`book_node`. Returns a
    conflict when the node isn't a supplier-bookable source (wrong source, no id,
    or supplier booking disabled) and surfaces an upstream failure as a conflict.
    """
    registry = registry or get_registry()
    settings = settings or get_settings()
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()
    supplier = _supplier_booking_provider(settings, node, registry)
    if supplier is None or not node.source_id:
        return _conflict("node_not_supplier_bookable")
    try:
        return await supplier.check_availability(
            source_id=node.source_id,
            start=start,
            end=end,
            currency=currency,
            ctx=InventoryCtx(actor_kind=actor.kind.value, actor_id=actor.actor_id),
        )
    except SupplierBookingError as exc:
        logger.warning(
            "booking.supplier.availability_failed",
            extra={"node_id": str(node_id), "source": node.source, "reason": exc.reason},
        )
        return _conflict("supplier_availability_failed")


async def book_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    override_unpaid: bool = False,
    supplier_selection: SupplierSelection | None = None,
    registry: InventoryProviderRegistry | None = None,
    settings: Settings | None = None,
) -> BookingView | ItineraryError:
    """Move an approved node to ``booked`` — the money gate.

    Requires a covering **paid** invoice line for the node (Σ paid lines ≥ the
    booked amount, same currency). With ``override_unpaid`` an advisor may book
    against a merely *issued* line instead; that's recorded on the booking and
    logged (D-PAY override). A flight node additionally requires a *fresh*
    (non-expired) offer — its booked amount is that re-priced figure (D024).

    When the node's source is a real bookable supplier (Bokun) and supplier
    booking is enabled, the gate additionally RESERVES + CONFIRMS the
    ``supplier_selection`` slot upstream (payment already cleared), advancing the
    node straight to ``confirmed`` with the returned confirmation code — no manual
    :func:`record_confirmation` step. Fail-closed: any supplier failure returns a
    conflict with nothing written locally, so the collected payment stays
    refundable and no phantom booking is recorded.
    """
    registry = registry or get_registry()
    settings = settings or get_settings()
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()
    # A node already booked reports that clearly (rather than "not approved",
    # which is true only because booking already moved it past approved).
    if await _booking_for(session, node_id) is not None:
        return _conflict("already_booked")
    if node.status is not _BOOKABLE_FROM:
        return _conflict("node_not_approved")

    # 1. The booked amount: a flight re-prices off a fresh offer; everything else
    #    books at its static B4 cost, with per-person costs expanded by party size.
    party_size = await resolve_party_size(session, itinerary_id)
    offer: NodeOffer | None = None
    if node.type is NodeType.flight:
        offer = await _latest_offer(session, node_id)
        if offer is None:
            return _conflict("offer_required")
        if _offer_expired(offer, at=_now()):
            return _conflict("offer_expired")
        amount, currency = offer.amount, offer.currency
    else:
        if node.cost_amount is None or node.cost_currency is None:
            return _err("node_has_no_cost")
        amount = effective_node_cost(node.cost_amount, node.cost_kind, party_size)
        currency = node.cost_currency

    # 2. The money gate: a covering paid line (or, on override, a covering issued one).
    used_override = False
    line_id = None
    if (
        await _node_paid_coverage(session, node_id, currency, statuses=[InvoiceStatus.paid])
        >= amount
    ):
        line_id = await _pick_covering_line(
            session, node_id, currency, statuses=[InvoiceStatus.paid]
        )
    elif (
        override_unpaid
        and await _node_paid_coverage(
            session, node_id, currency, statuses=[InvoiceStatus.paid, InvoiceStatus.issued]
        )
        >= amount
    ):
        used_override = True
        line_id = await _pick_covering_line(
            session, node_id, currency, statuses=[InvoiceStatus.paid, InvoiceStatus.issued]
        )
    else:
        return _conflict("node_not_paid")

    # 2b. Real supplier booking (Bokun): with payment secured, RESERVE then CONFIRM
    #     the chosen slot upstream. Fail-closed — any supplier failure returns a
    #     conflict with NOTHING written locally (no session writes happen before
    #     this point), so the money stays collected + refundable and we never record
    #     a booking the supplier didn't actually make. A confirmed supplier booking
    #     advances the node straight to ``confirmed`` (skips manual confirmation).
    supplier = _supplier_booking_provider(settings, node, registry)
    supplier_ref: str | None = None
    supplier_source: str | None = None
    supplier_booking_id: str | None = None
    supplier_selection_snapshot: dict[str, Any] | None = None
    supplier_raw: dict[str, Any] | None = None
    node_target_status = NodeStatus.booked
    confirmed_at: datetime | None = None
    if supplier is not None:
        if supplier_selection is None:
            return _conflict("supplier_selection_required")
        # The node is authoritative for WHICH activity is booked — rebind the
        # selection's source_id to it so a client can't book a different activity
        # than the node represents.
        selection = replace(
            supplier_selection, source_id=node.source_id or supplier_selection.source_id
        )
        ctx = InventoryCtx(actor_kind=actor.kind.value, actor_id=actor.actor_id)
        try:
            reservation = await supplier.reserve(selection=selection, ctx=ctx)
        except SupplierBookingError as exc:
            logger.warning(
                "booking.supplier.reserve_failed",
                extra={"node_id": str(node_id), "source": node.source, "reason": exc.reason},
            )
            return _conflict("supplier_reserve_failed")
        try:
            record = await supplier.confirm(
                confirmation_code=reservation.confirmation_code, ctx=ctx
            )
        except SupplierBookingError as exc:
            # Release the hold so inventory isn't stranded for its ~30-min window.
            try:
                await supplier.abort(confirmation_code=reservation.confirmation_code, ctx=ctx)
            except SupplierBookingError:
                logger.warning(
                    "booking.supplier.abort_failed",
                    extra={"node_id": str(node_id), "source": node.source},
                )
            logger.warning(
                "booking.supplier.confirm_failed",
                extra={"node_id": str(node_id), "source": node.source, "reason": exc.reason},
            )
            return _conflict("supplier_confirm_failed")
        supplier_ref = record.confirmation_code
        supplier_source = node.source
        supplier_booking_id = record.booking_id or reservation.booking_id
        supplier_selection_snapshot = selection.as_dict()
        supplier_raw = record.raw
        node_target_status = NodeStatus.confirmed
        confirmed_at = _now()

    # 3. Commit the booking + flip the node, in one transaction with history.
    booking = Booking(
        node_id=node_id,
        offer_id=offer.id if offer is not None else None,
        invoice_line_item_id=line_id,
        amount=amount,
        currency=currency,
        override_unpaid=used_override,
        booked_by=actor.user_id,
        booked_at=_now(),
        supplier_ref=supplier_ref,
        supplier_source=supplier_source,
        supplier_booking_id=supplier_booking_id,
        supplier_selection=supplier_selection_snapshot,
        supplier_raw=supplier_raw,
        confirmed_at=confirmed_at,
    )
    session.add(booking)
    before = _snapshot_node(node)
    node.status = node_target_status
    await session.flush()
    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="update",
        actor=actor,
        before=before,
        after=_snapshot_node(node),
    )
    await session.commit()
    if used_override:
        logger.warning(
            "booking.override_unpaid",
            extra={
                "node_id": str(node_id),
                "booking_id": str(booking.id),
                "actor_kind": actor.kind.value,
                "actor_id": actor.actor_id,
            },
        )
    logger.info(
        "booking.create",
        extra={
            "node_id": str(node_id),
            "booking_id": str(booking.id),
            "override_unpaid": used_override,
            "supplier_booked": supplier is not None,
            "actor_kind": actor.kind.value,
        },
    )
    # Compare the booked amount against the party-size-expanded B4 cost so an
    # expanded per-person node doesn't read as a spurious re-price; a flight's
    # cost_kind is ``total`` so its expanded base is unchanged.
    cost_baseline = (
        effective_node_cost(node.cost_amount, node.cost_kind, party_size)
        if node.cost_amount is not None
        else None
    )
    reprice_delta = _reprice_delta(amount, cost_baseline, node.cost_currency, currency)
    return BookingView(
        booking=booking,
        node_status=node.status,
        offer=offer,
        reprice_delta=reprice_delta,
    )


def _reprice_delta(
    booked_amount: Decimal,
    cost_amount: Decimal | None,
    cost_currency: str | None,
    currency: str,
) -> Decimal | None:
    """``booked − B4 cost`` when comparable and different, else None."""
    if cost_amount is None or cost_currency != currency:
        return None
    delta = booked_amount - cost_amount
    return delta if delta != _ZERO else None


async def record_confirmation(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    supplier_ref: str,
    change_cancel_terms: str | None = None,
) -> BookingView | ItineraryError:
    """Record a supplier confirmation # → advance ``booked`` to ``confirmed``."""
    supplier_ref = supplier_ref.strip()
    if not supplier_ref:
        return _err("supplier_ref_required")
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()
    if node.status is not NodeStatus.booked:
        return _conflict("node_not_booked")
    booking = await _booking_for(session, node_id)
    if booking is None:
        return _conflict("no_booking")

    booking.supplier_ref = supplier_ref
    if change_cancel_terms is not None:
        booking.change_cancel_terms = change_cancel_terms
    booking.confirmed_at = _now()
    before = _snapshot_node(node)
    node.status = NodeStatus.confirmed
    await session.flush()
    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="update",
        actor=actor,
        before=before,
        after=_snapshot_node(node),
    )
    await session.commit()
    logger.info(
        "booking.confirm",
        extra={"node_id": str(node_id), "booking_id": str(booking.id)},
    )
    return BookingView(
        booking=booking,
        node_status=node.status,
        offer=None,
        reprice_delta=None,
    )


async def get_booking(session: AsyncSession, node_id: uuid.UUID) -> Booking | None:
    return await _booking_for(session, node_id)


# ── Cancel + refund a booking ────────────────────────────────────────────────


async def cancel_booking(
    session: AsyncSession,
    actor: ActorContext,
    gateway: PaymentGateway | None,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    reason: str | None = None,
    registry: InventoryProviderRegistry | None = None,
) -> BookingView | ItineraryError:
    """Cancel a booked/confirmed node: cancel any real supplier booking, refund its
    covering payment, reverse the charge line, and demote the node to ``approved``.

    Money movement: a settled covering charge is **refunded**, an unsettled one
    **voided**; an ``override_unpaid`` booking (no money collected) cancels with
    ``refund_status=not_applicable`` and no gateway call. Fail-closed — if the
    gateway is down (raises) or declines, the whole cancel rolls back so the
    ledger never claims a refund that didn't happen. The node demotes through the
    same firmed→approved transition the G1 status gate permits an advisor, so a
    re-booking goes back through the money gate; reconcile stays balanced because
    the demoted node leaves the booked-sum and the reversal nets its coverage.

    A booking with a real supplier leg (Bokun) is cancelled UPSTREAM FIRST — before
    any refund — so we never return the traveler's money while the operator still
    holds the booking. That call is idempotent (an already-gone booking resolves as
    cancelled), so a retry after a refund failure re-cancels harmlessly.
    """
    registry = registry or get_registry()
    node = await _load_node(session, itinerary_id, node_id)
    if node is None:
        return _not_found()
    if node.status not in _BOOKED_STATUSES:
        return _conflict("node_not_booked")
    booking = await _booking_for(session, node_id)
    if booking is None:
        return _conflict("no_booking")

    # Cancel the real supplier booking FIRST (no local writes yet, so a failure just
    # returns). A booking placed upstream MUST be cancellable upstream: if it has a
    # supplier leg but no bookable provider is registered, refuse rather than refund
    # into an orphaned operator booking.
    if booking.supplier_booking_id:
        supplier = _supplier_provider_for_booking(booking, registry)
        if supplier is None:
            logger.warning(
                "booking.cancel.supplier_unavailable",
                extra={"node_id": str(node_id), "source": booking.supplier_source},
            )
            return _conflict("supplier_provider_unavailable")
        try:
            await supplier.cancel(
                booking_id=booking.supplier_booking_id,
                confirmation_code=booking.supplier_ref or "",
                ctx=InventoryCtx(actor_kind=actor.kind.value, actor_id=actor.actor_id),
            )
        except SupplierBookingError as exc:
            logger.warning(
                "booking.cancel.supplier_failed",
                extra={
                    "node_id": str(node_id),
                    "source": booking.supplier_source,
                    "reason": exc.reason,
                },
            )
            return _conflict("supplier_cancel_failed")

    # Resolve the refund target: the settled gateway charge that covered this
    # booking. An override (issued, unpaid) booking has none — nothing to return.
    covering_invoice_id = (
        await _covering_invoice_id(session, booking.invoice_line_item_id)
        if booking.invoice_line_item_id is not None
        else None
    )
    payment = (
        await _latest_succeeded_payment(session, covering_invoice_id)
        if covering_invoice_id is not None
        else None
    )

    # Capture ids now: a rollback below would expire the ORM objects, and reading
    # ``booking.id`` after that would trigger a sync lazy-load.
    booking_id = booking.id
    booking_amount = booking.amount
    booking_currency = booking.currency

    refund_status = RefundStatus.not_applicable
    refund_ref: str | None = None
    refund_payment: Payment | None = None

    if not booking.override_unpaid and payment is not None and payment.processor_transaction_id:
        if gateway is None:
            return _conflict("payments_unconfigured")
        refund_ref = new_refund_reference(booking_id)
        try:
            async with span("payment.gateway.refund", metric=True, gateway=gateway.name):
                result = await anyio.to_thread.run_sync(
                    partial(
                        gateway.refund,
                        processor_transaction_id=payment.processor_transaction_id,
                        amount=booking_amount,
                        reference=refund_ref,
                    )
                )
        except PaymentGatewayError as exc:
            # Outcome unknown (timeout/network) — undo nothing, let the advisor retry.
            await session.rollback()
            logger.warning(
                "booking.cancel.gateway_error",
                extra={
                    "node_id": str(node_id),
                    "booking_id": str(booking_id),
                    "gateway": gateway.name,
                    "reason": exc.reason,
                    "actor_kind": actor.kind.value,
                },
            )
            emit_metric("payment.gateway_error", 1, dimensions={"Gateway": gateway.name})
            return _conflict("refund_gateway_unavailable")
        if not result.ok:
            # Fail-closed: never undo the booking if we couldn't return the money.
            await session.rollback()
            return _conflict("refund_declined")
        refund_status = RefundStatus.refunded if result.kind == "refund" else RefundStatus.voided
        refund_payment = Payment(
            invoice_id=covering_invoice_id,
            amount=booking_amount,
            currency=booking_currency,
            status=PaymentStatus.refunded,
            gateway=gateway.name,
            gateway_reference=refund_ref,
            processor_transaction_id=result.processor_transaction_id,
            processor_response=result.processor_response,
            raw=result.raw,
        )
        session.add(refund_payment)
        await session.flush()

    # Reverse the covering charge line so the ledger reflects the undone booking.
    if booking.invoice_line_item_id is not None:
        original = (
            await session.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.id == booking.invoice_line_item_id)
            )
        ).scalar_one_or_none()
        if original is not None and original.kind is not InvoiceLineKind.reversal:
            already_reversed = (
                await session.execute(
                    select(InvoiceLineItem.id).where(
                        InvoiceLineItem.reverses_line_item_id == original.id
                    )
                )
            ).scalar_one_or_none()
            if already_reversed is None:
                session.add(
                    build_reversal_line(
                        actor,
                        original=original,
                        description=f"Refund of: {original.description}",
                    )
                )

    # Demote the node — the firmed→approved transition the G1 gate permits an
    # advisor (done inline like book_node, not bypassing the gate).
    before = _snapshot_node(node)
    node.status = _BOOKABLE_FROM
    refunded = refund_status in (RefundStatus.refunded, RefundStatus.voided)
    booking.cancelled_at = _now()
    booking.cancelled_by = actor.user_id
    booking.cancel_reason = reason
    booking.refund_status = refund_status
    booking.refund_amount = booking_amount if refunded else _ZERO
    booking.refund_currency = booking_currency
    booking.refund_gateway_ref = refund_ref
    if refund_payment is not None:
        booking.refund_payment_id = refund_payment.id
    await session.flush()
    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="update",
        actor=actor,
        before=before,
        after=_snapshot_node(node),
    )
    await session.commit()
    # Never log the refund cross-ref / processor id / raw payload.
    logger.info(
        "booking.cancel",
        extra={
            "node_id": str(node_id),
            "booking_id": str(booking_id),
            "refund_status": refund_status.value,
            "actor_kind": actor.kind.value,
        },
    )
    return BookingView(
        booking=booking,
        node_status=node.status,
        offer=None,
        reprice_delta=None,
    )


# ── The reconciliation invariant ─────────────────────────────────────────────


async def reconcile_itinerary(
    session: AsyncSession, itinerary_id: uuid.UUID
) -> ReconciliationReport:
    """Σ(paid invoice lines for booked nodes) ⇔ Σ(booked node amounts), by currency.

    For every booked/confirmed node we compare its booked amount (the re-priced
    figure recorded on its ``bookings`` row) against its paid invoice coverage.
    A mismatch is surfaced per node (``booked_unpaid`` / ``undercharged`` /
    ``overcharged``) and rolls up into a per-currency balance. The whole report
    is ``balanced`` only when every currency balances and there are no per-node
    violations — the assertion the e2e + verify script check.
    """
    bookings = list(
        (
            await session.execute(
                select(Booking)
                .join(Node, Node.id == Booking.node_id)
                .where(
                    Node.itinerary_id == itinerary_id,
                    Node.status.in_(list(_BOOKED_STATUSES)),
                    Booking.cancelled_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    paid_by_ccy: dict[str, Decimal] = {}
    booked_by_ccy: dict[str, Decimal] = {}
    violations: list[ReconciliationViolation] = []

    for booking in bookings:
        ccy = booking.currency
        paid = await _node_paid_coverage(
            session, booking.node_id, ccy, statuses=[InvoiceStatus.paid]
        )
        booked_by_ccy[ccy] = booked_by_ccy.get(ccy, _ZERO) + booking.amount
        paid_by_ccy[ccy] = paid_by_ccy.get(ccy, _ZERO) + paid
        if paid != booking.amount:
            if paid <= _ZERO:
                code = "booked_unpaid"
            elif paid < booking.amount:
                code = "undercharged"
            else:
                code = "overcharged"
            violations.append(
                ReconciliationViolation(
                    node_id=booking.node_id,
                    code=code,
                    currency=ccy,
                    booked_amount=booking.amount,
                    paid_amount=paid,
                )
            )

    rows = [
        ReconciliationRow(
            currency=ccy,
            paid_total=paid_by_ccy.get(ccy, _ZERO),
            booked_total=booked_by_ccy.get(ccy, _ZERO),
            balanced=paid_by_ccy.get(ccy, _ZERO) == booked_by_ccy.get(ccy, _ZERO),
        )
        for ccy in sorted(set(paid_by_ccy) | set(booked_by_ccy))
    ]
    balanced = not violations and all(row.balanced for row in rows)
    return ReconciliationReport(rows=rows, violations=violations, balanced=balanced)
