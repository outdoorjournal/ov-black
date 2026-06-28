"""Money gate + booking workflow (M005/I3).

Two layers, mirroring ``test_invoices.py``:

1. Integration tests against a local Supabase Postgres — the money gate
   (approved → booked needs a covering PAID line; an advisor override books on a
   merely *issued* line, logged), the flight re-price-before-book offer lifecycle
   (live provider via the mock ``get_detail`` contract + the snapshot fallback +
   expiry refusal), record-confirmation (booked → confirmed), the update_node
   bypass refusal, and the reconciliation invariant (Σ paid lines ⇔ Σ booked).
2. Router tests (service stubbed) — advisor-only writes, 401 without a JWT, the
   409 money-gate mapping, and the owner/advisor reconciliation read gate.

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.inventory.registry import InventoryCtx, InventoryProvider, InventoryProviderRegistry
from app.inventory.schemas import FlightItem, InventoryItem, Price
from app.models import (
    Booking,
    CostKind,
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    NodeOffer,
    NodeStatus,
    NodeType,
    Payment,
    PaymentStatus,
    RefundStatus,
)
from app.payments.base import PaymentGatewayError, RefundResult
from app.payments.braintree_gateway import FakeGateway
from app.services.bookings import (
    BookingView,
    ReconciliationReport,
    book_node,
    cancel_booking,
    reconcile_itinerary,
    record_confirmation,
    refresh_offer,
)
from app.services.invoices import (
    add_line_item_from_node,
    create_invoice,
    issue_invoice,
    mark_invoice_paid,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    add_node,
    create_itinerary,
    update_node,
)
from app.services.payments import pay_invoice
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"bk-{kind.value}")


# ── Integration harness ──────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(*itinerary_ids: uuid.UUID) -> None:
    # bookings / node_offers cascade off nodes (→ itinerary); invoices cascade off
    # the itinerary. node/edge history have no FK so they're cleared explicitly.
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(
                    text("delete from public.edge_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
    finally:
        await engine.dispose()


async def _priced_node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    amount: str,
    currency: str = "USD",
    title: str = "Hotel",
    node_type: NodeType = NodeType.hotel,
    source: str | None = None,
    source_id: str | None = None,
) -> Any:
    node = await add_node(
        session,
        _actor(),
        itinerary_id=itinerary_id,
        type=node_type,
        status=NodeStatus.approved,
        title=title,
        source=source,
        source_id=source_id,
        cost_amount=Decimal(amount),
        cost_currency=currency,
        cost_kind=CostKind.total,
    )
    assert not isinstance(node, ItineraryError)
    return node


async def _pay_node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    *,
    paid: bool = True,
) -> Invoice:
    """Assemble a one-line invoice charging the node, issue it, optionally pay it."""
    invoice = await create_invoice(
        session, _actor(), itinerary_id=itinerary_id, label="Deposit", currency="USD"
    )
    assert isinstance(invoice, Invoice)
    charge = await add_line_item_from_node(
        session, _actor(), invoice_id=invoice.id, node_id=node_id
    )
    assert not isinstance(charge, ItineraryError)
    issued = await issue_invoice(session, _actor(), invoice_id=invoice.id)
    assert isinstance(issued, Invoice)
    if paid:
        marked = await mark_invoice_paid(session, invoice_id=invoice.id)
        assert isinstance(marked, Invoice)
        await session.commit()
    return invoice


async def _pay_node_via_gateway(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    gateway: Any,
) -> Invoice:
    """Charge a node's invoice through the gateway so a settled Payment exists to
    refund (unlike ``_pay_node``, which marks paid without a Payment row)."""
    invoice = await create_invoice(
        session, _actor(), itinerary_id=itinerary_id, label="Deposit", currency="USD"
    )
    assert isinstance(invoice, Invoice)
    charge = await add_line_item_from_node(
        session, _actor(), invoice_id=invoice.id, node_id=node_id
    )
    assert not isinstance(charge, ItineraryError)
    issued = await issue_invoice(session, _actor(), invoice_id=invoice.id)
    assert isinstance(issued, Invoice)
    payment = await pay_invoice(
        session,
        _actor(),
        gateway,
        invoice_id=invoice.id,
        payment_method_nonce="fake-valid-nonce",
    )
    assert isinstance(payment, Payment)
    return invoice


class _DeclineRefundGateway:
    """A gateway whose refund cleanly declines (settled outcome, ok=False)."""

    name = "fake"

    def generate_client_token(self) -> str:
        return "t"

    def sale(self, **_kw: Any) -> Any:  # pragma: no cover — unused by cancel
        raise NotImplementedError

    def refund(self, *, processor_transaction_id: str, amount: Any, reference: str) -> RefundResult:
        return RefundResult(ok=False, status="failed", kind="refund", processor_response="declined")


class _ErrorRefundGateway:
    """A gateway whose refund raises — the outcome-unknown (infra) path."""

    name = "fake"

    def generate_client_token(self) -> str:
        return "t"

    def sale(self, **_kw: Any) -> Any:  # pragma: no cover — unused by cancel
        raise NotImplementedError

    def refund(self, *, processor_transaction_id: str, amount: Any, reference: str) -> RefundResult:
        raise PaymentGatewayError("boom")


# ── A stand-in provider with the same get_detail re-price contract as Duffel ──


class _RepriceProvider(InventoryProvider):
    """Returns a (re-priced) FlightItem from ``get_detail`` — the live path."""

    source = "mockair"

    def __init__(self, item: InventoryItem | None) -> None:
        self._item = item

    async def search(self, **_kw: Any) -> list[InventoryItem]:
        return []

    async def get_detail(self, *, source_id: str, ctx: InventoryCtx) -> InventoryItem | None:
        return self._item


def _registry_with(item: InventoryItem | None) -> InventoryProviderRegistry:
    reg = InventoryProviderRegistry()
    reg.register(_RepriceProvider(item))
    return reg


# ── The money gate: blocks unpaid, books paid, confirms ──────────────────────


@integration
@pytest.mark.asyncio
async def test_money_gate_blocks_unpaid_then_books_paid_and_confirms(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="gate")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")

        # 1. An unpaid approved node cannot be booked.
        blocked = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(blocked, ItineraryError)
        assert blocked.detail == "node_not_paid"

        # 2. After a covering paid line, it books at its B4 cost.
        await _pay_node(db_session, itin.id, node.id, paid=True)
        view = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(view, BookingView)
        assert view.node_status is NodeStatus.booked
        assert view.booking.amount == Decimal("1000.00")
        assert view.booking.override_unpaid is False
        assert view.booking.invoice_line_item_id is not None
        assert view.reprice_delta is None  # booked == B4 cost

        # 3. One live booking per node.
        again = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(again, ItineraryError)
        assert again.detail == "already_booked"

        # 4. Record a supplier confirmation → confirmed.
        confirmed = await record_confirmation(
            db_session, _actor(), itinerary_id=itin.id, node_id=node.id, supplier_ref="ABC123"
        )
        assert isinstance(confirmed, BookingView)
        assert confirmed.node_status is NodeStatus.confirmed
        assert confirmed.booking.supplier_ref == "ABC123"
        assert confirmed.booking.confirmed_at is not None

        # 5. The reconciliation invariant holds.
        report = await reconcile_itinerary(db_session, itin.id)
        assert isinstance(report, ReconciliationReport)
        assert report.balanced is True
        assert report.violations == []
        assert any(
            r.currency == "USD" and r.booked_total == Decimal("1000.00") for r in report.rows
        )
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_per_person_node_books_and_reconciles_expanded_by_party_size(
    db_session: AsyncSession,
) -> None:
    """A per_person cost expands consistently across the charge line, the booked
    amount, and reconcile — so the invariant holds and the expansion doesn't read
    as a re-price."""
    itin = await create_itinerary(db_session, _actor(), title="per-person gate")
    try:
        # A party of two travelers.
        party_id = uuid.uuid4()
        await db_session.execute(
            text("insert into public.parties (id, itinerary_id, label) values (:p, :i, 'all')"),
            {"p": party_id, "i": itin.id},
        )
        for name in ("a", "b"):
            await db_session.execute(
                text("insert into public.travelers (party_id, name) values (:p, :n)"),
                {"p": party_id, "n": name},
            )
        await db_session.commit()

        # A per_person node at 1000 → 2000 for two travelers.
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            status=NodeStatus.approved,
            title="Private guide",
            cost_amount=Decimal("1000.00"),
            cost_currency="USD",
            cost_kind=CostKind.per_person,
        )
        assert not isinstance(node, ItineraryError)

        # The charge line is assembled at the expanded amount, paid, then booked.
        await _pay_node(db_session, itin.id, node.id, paid=True)
        view = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(view, BookingView)
        assert view.booking.amount == Decimal("2000.00")
        assert view.reprice_delta is None  # the expansion must not read as a re-price

        report = await reconcile_itinerary(db_session, itin.id)
        assert isinstance(report, ReconciliationReport)
        assert report.balanced is True
        assert report.violations == []
    finally:
        await _cleanup(itin.id)


# ── Cancel + refund ──────────────────────────────────────────────────────────


async def _refunds_for_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> list[Payment]:
    return list(
        (
            await session.execute(
                select(Payment).where(
                    Payment.invoice_id == invoice_id,
                    Payment.status == PaymentStatus.refunded,
                )
            )
        )
        .scalars()
        .all()
    )


async def _reversals_for_node(session: AsyncSession, node_id: uuid.UUID) -> list[InvoiceLineItem]:
    return list(
        (
            await session.execute(
                select(InvoiceLineItem).where(
                    InvoiceLineItem.node_id == node_id,
                    InvoiceLineItem.kind == InvoiceLineKind.reversal,
                )
            )
        )
        .scalars()
        .all()
    )


@integration
@pytest.mark.asyncio
async def test_cancel_refunds_demotes_reverses_and_reconciles(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cancel")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")
        invoice = await _pay_node_via_gateway(db_session, itin.id, node.id, FakeGateway())
        booked = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(booked, BookingView)

        view = await cancel_booking(
            db_session, _actor(), FakeGateway(), itinerary_id=itin.id, node_id=node.id
        )
        assert isinstance(view, BookingView)
        assert view.node_status is NodeStatus.approved
        assert view.booking.refund_status is RefundStatus.refunded
        assert view.booking.refund_amount == Decimal("1000.00")
        assert view.booking.cancelled_at is not None

        refunds = await _refunds_for_invoice(db_session, invoice.id)
        assert len(refunds) == 1
        assert refunds[0].amount == Decimal("1000.00")

        reversals = await _reversals_for_node(db_session, node.id)
        assert len(reversals) == 1
        assert reversals[0].amount == Decimal("-1000.00")

        report = await reconcile_itinerary(db_session, itin.id)
        assert report.balanced is True
        assert report.violations == []
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_cancel_override_unpaid_is_not_applicable(
    db_session: AsyncSession,
) -> None:
    """A booking made against a merely *issued* line has no money to return."""
    itin = await create_itinerary(db_session, _actor(), title="cancel override")
    try:
        node = await _priced_node(db_session, itin.id, amount="500.00", title="Villa")
        # Issue (not pay) a covering line, then book with override.
        invoice = await create_invoice(
            db_session, _actor(), itinerary_id=itin.id, label="Dep", currency="USD"
        )
        assert isinstance(invoice, Invoice)
        await add_line_item_from_node(db_session, _actor(), invoice_id=invoice.id, node_id=node.id)
        await issue_invoice(db_session, _actor(), invoice_id=invoice.id)
        booked = await book_node(
            db_session, _actor(), itinerary_id=itin.id, node_id=node.id, override_unpaid=True
        )
        assert isinstance(booked, BookingView)

        # No gateway should be needed; pass one that would explode if called.
        view = await cancel_booking(
            db_session, _actor(), _ErrorRefundGateway(), itinerary_id=itin.id, node_id=node.id
        )
        assert isinstance(view, BookingView)
        assert view.node_status is NodeStatus.approved
        assert view.booking.refund_status is RefundStatus.not_applicable
        assert view.booking.refund_amount == Decimal("0.00")
        assert await _refunds_for_invoice(db_session, invoice.id) == []
        report = await reconcile_itinerary(db_session, itin.id)
        assert report.balanced is True
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_cancel_fails_closed_on_declined_refund(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cancel decline")
    itin_id = itin.id  # captured before a rollback below expires the ORM objects
    try:
        node = await _priced_node(db_session, itin_id, amount="1000.00", title="Aman")
        node_id = node.id
        await _pay_node_via_gateway(db_session, itin_id, node_id, FakeGateway())
        await book_node(db_session, _actor(), itinerary_id=itin_id, node_id=node_id)

        declined = await cancel_booking(
            db_session, _actor(), _DeclineRefundGateway(), itinerary_id=itin_id, node_id=node_id
        )
        assert isinstance(declined, ItineraryError)
        assert declined.detail == "refund_declined"

        # Nothing changed: the booking is intact and the node still booked.
        refreshed = await book_node(db_session, _actor(), itinerary_id=itin_id, node_id=node_id)
        assert isinstance(refreshed, ItineraryError)
        assert refreshed.detail == "already_booked"
    finally:
        await _cleanup(itin_id)


@integration
@pytest.mark.asyncio
async def test_cancel_rolls_back_on_gateway_error(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cancel error")
    itin_id = itin.id  # captured before a rollback below expires the ORM objects
    try:
        node = await _priced_node(db_session, itin_id, amount="1000.00", title="Aman")
        node_id = node.id
        await _pay_node_via_gateway(db_session, itin_id, node_id, FakeGateway())
        await book_node(db_session, _actor(), itinerary_id=itin_id, node_id=node_id)

        errored = await cancel_booking(
            db_session, _actor(), _ErrorRefundGateway(), itinerary_id=itin_id, node_id=node_id
        )
        assert isinstance(errored, ItineraryError)
        assert errored.detail == "refund_gateway_unavailable"
        # Node still booked; the booking row is not cancelled.
        again = await book_node(db_session, _actor(), itinerary_id=itin_id, node_id=node_id)
        assert isinstance(again, ItineraryError)
        assert again.detail == "already_booked"
    finally:
        await _cleanup(itin_id)


@integration
@pytest.mark.asyncio
async def test_cancel_refuses_unbooked_node(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cancel unbooked")
    try:
        node = await _priced_node(db_session, itin.id, amount="100.00", title="Idea")
        res = await cancel_booking(
            db_session, _actor(), FakeGateway(), itinerary_id=itin.id, node_id=node.id
        )
        assert isinstance(res, ItineraryError)
        assert res.detail == "node_not_booked"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_node_can_be_rebooked_after_cancel(
    db_session: AsyncSession,
) -> None:
    """The partial unique index allows a fresh booking once the prior is cancelled."""
    itin = await create_itinerary(db_session, _actor(), title="rebook")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")
        await _pay_node_via_gateway(db_session, itin.id, node.id, FakeGateway())
        await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        await cancel_booking(
            db_session, _actor(), FakeGateway(), itinerary_id=itin.id, node_id=node.id
        )

        # Re-pay (the first line was reversed) and re-book.
        await _pay_node_via_gateway(db_session, itin.id, node.id, FakeGateway())
        rebooked = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(rebooked, BookingView)
        assert rebooked.node_status is NodeStatus.booked
        report = await reconcile_itinerary(db_session, itin.id)
        assert report.balanced is True
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_cancel_does_not_leak_refund_refs_to_logs(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="cancel redact")
    try:
        node = await _priced_node(db_session, itin.id, amount="1000.00", title="Aman")
        await _pay_node_via_gateway(db_session, itin.id, node.id, FakeGateway())
        await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        with caplog.at_level(logging.INFO):
            view = await cancel_booking(
                db_session, _actor(), FakeGateway(), itinerary_id=itin.id, node_id=node.id
            )
        assert isinstance(view, BookingView)
        messages = [r.getMessage() for r in caplog.records]
        extras = [str(r.__dict__.get("refund_gateway_ref", "")) for r in caplog.records]
        blob = "\n".join(messages + extras)
        assert view.booking.refund_gateway_ref is not None
        assert view.booking.refund_gateway_ref not in blob
        assert "fake-refund-" not in blob  # the processor refund id never logged
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_override_books_on_issued_line_and_reconcile_flags_it(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="override")
    try:
        node = await _priced_node(db_session, itin.id, amount="500.00")
        await _pay_node(db_session, itin.id, node.id, paid=False)  # issued, NOT paid

        # No override → refused (only a paid line covers).
        refused = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(refused, ItineraryError)
        assert refused.detail == "node_not_paid"

        # Override → books on the issued line, flagged + logged.
        with caplog.at_level("WARNING"):
            view = await book_node(
                db_session, _actor(), itinerary_id=itin.id, node_id=node.id, override_unpaid=True
            )
        assert isinstance(view, BookingView)
        assert view.booking.override_unpaid is True
        assert any("booking.override_unpaid" in r.message for r in caplog.records)

        # Reconciliation surfaces it: the booked node has no PAID coverage.
        report = await reconcile_itinerary(db_session, itin.id)
        assert report.balanced is False
        assert any(v.node_id == node.id and v.code == "booked_unpaid" for v in report.violations)
    finally:
        await _cleanup(itin.id)


# ── Flight re-price-before-book (offers) ─────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_flight_requires_fresh_offer_then_books_via_snapshot(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="flight")
    try:
        node = await _priced_node(
            db_session, itin.id, amount="800.00", title="DL275", node_type=NodeType.flight
        )
        await _pay_node(db_session, itin.id, node.id, paid=True)

        # A flight can't book without a fresh offer.
        no_offer = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(no_offer, ItineraryError)
        assert no_offer.detail == "offer_required"

        # Snapshot re-price (no provider source) → a fresh quote off the B4 cost.
        offer = await refresh_offer(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            registry=_registry_with(None),
        )
        assert isinstance(offer, NodeOffer)
        assert offer.source == "snapshot"
        assert offer.amount == Decimal("800.00")
        assert offer.expires_at is not None

        view = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(view, BookingView)
        assert view.booking.offer_id == offer.id
        assert view.booking.amount == Decimal("800.00")
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_flight_reprices_live_via_provider_and_surfaces_delta(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(db_session, _actor(), title="reprice")
    try:
        node = await _priced_node(
            db_session,
            itin.id,
            amount="500.00",
            title="DL275",
            node_type=NodeType.flight,
            source="mockair",
            source_id="off_1",
        )
        # The held offer re-prices UP to 600 (mirrors a Duffel GET /air/offers/{id}).
        expires = (datetime.now(UTC) + timedelta(minutes=20)).isoformat()
        item = FlightItem(
            source="mockair",
            source_id="off_1",
            title="DL275",
            price=Price(amount_min=600.0, amount_max=600.0, currency="USD"),
            raw={"expires_at": expires},
        )
        offer = await refresh_offer(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            registry=_registry_with(item),
        )
        assert isinstance(offer, NodeOffer)
        assert offer.source == "mockair"
        assert offer.source_offer_id == "off_1"
        assert offer.amount == Decimal("600.00")
        assert offer.expires_at is not None

        # Pay the re-priced amount, then book — the delta vs B4 cost is surfaced.
        node.cost_amount = Decimal("600.00")
        await db_session.commit()
        await _pay_node(db_session, itin.id, node.id, paid=True)
        # cost back to 500 so the booked (600) vs B4 (500) delta shows.
        node.cost_amount = Decimal("500.00")
        await db_session.commit()

        view = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(view, BookingView)
        assert view.booking.amount == Decimal("600.00")
        assert view.reprice_delta == Decimal("100.00")
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_provider_offer_gone_is_conflict(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="gone")
    try:
        node = await _priced_node(
            db_session,
            itin.id,
            amount="500.00",
            node_type=NodeType.flight,
            source="mockair",
            source_id="off_x",
        )
        # get_detail returns None → the held offer lapsed; re-price refused.
        gone = await refresh_offer(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            registry=_registry_with(None),
        )
        assert isinstance(gone, ItineraryError)
        assert gone.detail == "offer_unavailable"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_expired_offer_refuses_booking(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="expired")
    try:
        node = await _priced_node(db_session, itin.id, amount="800.00", node_type=NodeType.flight)
        await _pay_node(db_session, itin.id, node.id, paid=True)
        offer = await refresh_offer(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            registry=_registry_with(None),
        )
        assert isinstance(offer, NodeOffer)
        # Force the held price to lapse.
        offer.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.commit()

        expired = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(expired, ItineraryError)
        assert expired.detail == "offer_expired"
    finally:
        await _cleanup(itin.id)


# ── The bypass is closed ─────────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_update_node_refuses_direct_booking_bypass(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="bypass")
    try:
        node = await _priced_node(db_session, itin.id, amount="100.00")

        for target in (NodeStatus.booked, NodeStatus.confirmed):
            res = await update_node(
                db_session,
                _actor(ActorKind.ADVISOR),
                itinerary_id=itin.id,
                node_id=node.id,
                status=target,
            )
            assert isinstance(res, ItineraryError)
            assert res.detail == "use_booking_flow"

        # Demotion OUT of a firmed status still works (the cancellation escape hatch):
        # seed booked directly, then update_node can move it back to approved.
        row = await db_session.get(type(node), node.id)
        assert row is not None
        row.status = NodeStatus.booked
        await db_session.commit()
        demoted = await update_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=itin.id,
            node_id=node.id,
            status=NodeStatus.approved,
        )
        assert not isinstance(demoted, ItineraryError)
        assert demoted.status is NodeStatus.approved
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_non_flight_without_cost_cannot_book(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="nocost")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            status=NodeStatus.approved,
            title="Tea ceremony",
        )
        assert not isinstance(node, ItineraryError)
        res = await book_node(db_session, _actor(), itinerary_id=itin.id, node_id=node.id)
        assert isinstance(res, ItineraryError)
        assert res.detail == "node_has_no_cost"
    finally:
        await _cleanup(itin.id)


# ── Router (service stubbed) ───────────────────────────────────────────────


@pytest.fixture()
def booking_routes(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub the booking endpoints' service + access collaborators."""
    from app.auth import AuthenticatedUser
    from app.auth_guards import require_advisor
    from app.db import get_session
    from app.main import app as fastapi_app
    from app.routers import bookings as rb

    returns: dict[str, Any] = {"is_advisor": True, "book_error": None, "cancel_error": None}

    def _booking_view(status: NodeStatus = NodeStatus.booked, **over: Any) -> BookingView:
        fields: dict[str, Any] = {
            "id": uuid.uuid4(),
            "node_id": uuid.uuid4(),
            "amount": Decimal("1000.00"),
            "currency": "USD",
            "override_unpaid": False,
            "booked_at": datetime.now(UTC),
        }
        fields.update(over)
        return BookingView(
            booking=Booking(**fields), node_status=status, offer=None, reprice_delta=None
        )

    async def _book(_s: Any, _a: Any, **_kw: Any) -> Any:
        err = returns.get("book_error")
        return err if err is not None else _booking_view()

    async def _cancel(_s: Any, _a: Any, _g: Any, **_kw: Any) -> Any:
        err = returns.get("cancel_error")
        if err is not None:
            return err
        return _booking_view(
            status=NodeStatus.approved,
            cancelled_at=datetime.now(UTC),
            refund_status=RefundStatus.refunded,
            refund_amount=Decimal("1000.00"),
        )

    async def _reconcile(_s: Any, _iid: uuid.UUID) -> ReconciliationReport:
        return ReconciliationReport(rows=[], violations=[], balanced=True)

    async def _assert_access(_s: Any, _u: Any, _iid: uuid.UUID) -> None:
        if not returns.get("is_advisor", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(rb.bookings_svc, "book_node", _book)
    monkeypatch.setattr(rb.bookings_svc, "cancel_booking", _cancel)
    monkeypatch.setattr(rb.bookings_svc, "reconcile_itinerary", _reconcile)
    monkeypatch.setattr(rb, "_assert_itinerary_access", _assert_access)

    async def _dep() -> Any:
        yield object()

    advisor_user = AuthenticatedUser(
        sub=str(uuid.uuid4()), email="a@x.com", role="authenticated", claims={}
    )

    async def _require_advisor() -> Any:
        if not returns.get("is_advisor", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="advisor_only")
        return advisor_user

    from app.routers.invoices import get_payment_gateway

    fastapi_app.dependency_overrides[get_session] = _dep
    fastapi_app.dependency_overrides[require_advisor] = _require_advisor
    fastapi_app.dependency_overrides[get_payment_gateway] = lambda: FakeGateway()
    try:
        yield {"returns": returns}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(require_advisor, None)
        fastapi_app.dependency_overrides.pop(get_payment_gateway, None)


def _headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


def test_book_endpoint_200(client: Any, booking_routes: Any, make_token: Any) -> None:
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/book",
        json={},
        headers=_headers(make_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_status"] == "booked"
    assert body["amount"] == "1000.00"


def test_book_endpoint_advisor_only_403(client: Any, booking_routes: Any, make_token: Any) -> None:
    booking_routes["returns"]["is_advisor"] = False
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/book",
        json={},
        headers=_headers(make_token),
    )
    assert resp.status_code == 403


def test_book_endpoint_requires_jwt(client: Any, booking_routes: Any) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/book", json={})
    assert resp.status_code == 401


def test_book_endpoint_money_gate_409(client: Any, booking_routes: Any, make_token: Any) -> None:
    from app.services.itineraries import ItineraryError, ItineraryOutcome

    booking_routes["returns"]["book_error"] = ItineraryError(
        outcome=ItineraryOutcome.CONFLICT, detail="node_not_paid"
    )
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/book",
        json={},
        headers=_headers(make_token),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "node_not_paid"


def test_cancel_endpoint_200(client: Any, booking_routes: Any, make_token: Any) -> None:
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/cancel",
        json={"reason": "client changed plans"},
        headers=_headers(make_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["node_status"] == "approved"
    assert body["refund_status"] == "refunded"
    assert body["refund_amount"] == "1000.00"


def test_cancel_endpoint_advisor_only_403(
    client: Any, booking_routes: Any, make_token: Any
) -> None:
    booking_routes["returns"]["is_advisor"] = False
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/cancel",
        json={},
        headers=_headers(make_token),
    )
    assert resp.status_code == 403


def test_cancel_endpoint_requires_jwt(client: Any, booking_routes: Any) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/cancel", json={})
    assert resp.status_code == 401


def test_cancel_endpoint_conflict_409(client: Any, booking_routes: Any, make_token: Any) -> None:
    from app.services.itineraries import ItineraryError, ItineraryOutcome

    booking_routes["returns"]["cancel_error"] = ItineraryError(
        outcome=ItineraryOutcome.CONFLICT, detail="refund_declined"
    )
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/nodes/{uuid.uuid4()}/cancel",
        json={},
        headers=_headers(make_token),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "refund_declined"


def test_reconciliation_endpoint_200_for_advisor(
    client: Any, booking_routes: Any, make_token: Any
) -> None:
    resp = client.get(f"/itinerary/{uuid.uuid4()}/reconciliation", headers=_headers(make_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["balanced"] is True


def test_reconciliation_endpoint_forbidden_for_stranger(
    client: Any, booking_routes: Any, make_token: Any
) -> None:
    booking_routes["returns"]["is_advisor"] = False
    resp = client.get(f"/itinerary/{uuid.uuid4()}/reconciliation", headers=_headers(make_token))
    assert resp.status_code == 403
