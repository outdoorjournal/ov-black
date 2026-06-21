"""First-class node cost — M002/B4 (decision D-COST, migration 0016).

Two layers, mirroring test_itineraries.py:

1. Pure unit tests for :func:`cost_from_inventory_item` (provider price →
   node cost triple) and the :func:`_check_cost` both-or-neither guard.
2. Integration tests (gated on local Supabase) that exercise the real
   service + columns: ``add_node`` persists cost, the graph-read CTE surfaces
   it, ``update_node`` edits/clears it (and rejects a half-specified cost),
   and :func:`sum_node_costs` totals per currency with the right filters.
"""

from __future__ import annotations

import socket
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.inventory.schemas import (
    ExperienceItem,
    FlightItem,
    HotelItem,
    MealItem,
    Price,
)
from app.models import CostKind, NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    _check_cost,
    add_node,
    create_itinerary,
    get_itinerary_graph,
    update_node,
)
from app.services.node_cost import (
    NodeCost,
    cost_from_inventory_item,
    sum_node_costs,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ── Pure unit tests: cost_from_inventory_item ──────────────────────────────


def _price(amount_min=None, amount_max=None, currency=None) -> Price:
    return Price(amount_min=amount_min, amount_max=amount_max, currency=currency)


def test_flight_cost_is_total() -> None:
    item = FlightItem(
        source="duffel",
        source_id="off_1",
        title="LAX → HND",
        price=_price(6420.5, 6420.5, "USD"),
    )
    cost = cost_from_inventory_item(item)
    assert cost == NodeCost(Decimal("6420.50"), "USD", CostKind.total)


def test_hotel_cost_is_total() -> None:
    item = HotelItem(
        source="ratehawk",
        source_id="h_1",
        title="Grand Hotel",
        price=_price(999.0, 999.0, "EUR"),
    )
    cost = cost_from_inventory_item(item)
    assert cost is not None
    assert cost.kind is CostKind.total
    assert cost.amount == Decimal("999.00")
    assert cost.currency == "EUR"


def test_experience_cost_is_per_person() -> None:
    """OV quotes a per-person ``minPrice``; we headline off amount_min."""
    item = ExperienceItem(
        source="ov",
        source_id="trip_1",
        title="Dolomites traverse",
        price=_price(1200.0, 1800.0, "USD"),
    )
    cost = cost_from_inventory_item(item)
    assert cost == NodeCost(Decimal("1200.00"), "USD", CostKind.per_person)


def test_falls_back_to_amount_max_when_min_absent() -> None:
    item = ExperienceItem(
        source="ov",
        source_id="trip_2",
        title="Half-day sail",
        price=_price(None, 450.0, "USD"),
    )
    cost = cost_from_inventory_item(item)
    assert cost is not None
    assert cost.amount == Decimal("450.00")


def test_quantizes_to_two_places() -> None:
    item = HotelItem(
        source="ratehawk",
        source_id="h_2",
        title="Pensione",
        price=_price(99.999, None, "EUR"),
    )
    cost = cost_from_inventory_item(item)
    assert cost is not None
    assert cost.amount == Decimal("100.00")  # ROUND_HALF_UP


def test_no_price_yields_none() -> None:
    """A Google-Places meal carries no bookable amount → no cost."""
    item = MealItem(source="google_places", source_id="pl_1", title="Sushi Saito")
    assert cost_from_inventory_item(item) is None


def test_amount_without_currency_yields_none() -> None:
    item = ExperienceItem(
        source="ov",
        source_id="trip_3",
        title="Mystery",
        price=_price(500.0, 500.0, None),
    )
    assert cost_from_inventory_item(item) is None


def test_currency_without_amount_yields_none() -> None:
    item = ExperienceItem(
        source="ov",
        source_id="trip_4",
        title="Mystery",
        price=_price(None, None, "USD"),
    )
    assert cost_from_inventory_item(item) is None


# ── Pure unit tests: _check_cost guard ─────────────────────────────────────


def test_check_cost_accepts_both_set() -> None:
    assert _check_cost(Decimal("10.00"), "USD") is None


def test_check_cost_accepts_both_unset() -> None:
    assert _check_cost(None, None) is None


def test_check_cost_rejects_amount_without_currency() -> None:
    err = _check_cost(Decimal("10.00"), None)
    assert err is not None
    assert err.outcome is ItineraryOutcome.VALIDATION_ERROR


def test_check_cost_rejects_currency_without_amount() -> None:
    err = _check_cost(None, "USD")
    assert err is not None
    assert err.outcome is ItineraryOutcome.VALIDATION_ERROR


# ── Integration tests (against local Supabase Postgres) ────────────────────


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


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(itinerary_id: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.node_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
    finally:
        await engine.dispose()


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="test-cost")


@integration
@pytest.mark.asyncio
async def test_add_node_persists_cost_and_graph_read_surfaces_it(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="cost add")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.flight,
            status=NodeStatus.proposed,
            title="LAX → HND",
            source="duffel",
            source_id="off_1",
            cost_amount=Decimal("6420.50"),
            cost_currency="USD",
            cost_kind=CostKind.total,
        )
        assert not isinstance(node, ItineraryError)
        assert node.cost_amount == Decimal("6420.50")

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        (read,) = view.nodes
        assert read.cost_amount == Decimal("6420.50")
        assert read.cost_currency == "USD"
        assert read.cost_kind is CostKind.total
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_add_node_rejects_half_specified_cost(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="cost half")
    try:
        result = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            title="No currency",
            cost_amount=Decimal("100.00"),
            cost_currency=None,
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_update_node_edits_and_clears_cost(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="cost edit")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            title="Stay",
            cost_amount=Decimal("500.00"),
            cost_currency="USD",
            cost_kind=CostKind.total,
        )
        assert not isinstance(node, ItineraryError)

        # Advisor edits the amount.
        edited = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            cost_amount=Decimal("550.00"),
        )
        assert not isinstance(edited, ItineraryError)
        assert edited.cost_amount == Decimal("550.00")
        assert edited.cost_currency == "USD"

        # Clearing must drop both halves together.
        cleared = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            cost_amount=None,
            cost_currency=None,
            cost_kind=None,
        )
        assert not isinstance(cleared, ItineraryError)
        assert cleared.cost_amount is None
        assert cleared.cost_currency is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_update_node_rejects_clearing_only_amount(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="cost edit bad")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            title="Stay",
            cost_amount=Decimal("500.00"),
            cost_currency="USD",
        )
        assert not isinstance(node, ItineraryError)
        result = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            cost_amount=None,  # leaves currency dangling
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_sum_node_costs_groups_by_currency_and_filters(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="cost sum")

    async def _node(amount, currency, *, status=NodeStatus.approved, selected=True):
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            status=status,
            title="n",
            cost_amount=Decimal(amount) if amount is not None else None,
            cost_currency=currency,
            cost_kind=CostKind.total if amount is not None else None,
        )
        assert not isinstance(node, ItineraryError)
        if not selected:
            await db_session.execute(
                text("update public.nodes set is_selected_alt = false where id = :i"),
                {"i": node.id},
            )
            await db_session.commit()
        return node

    try:
        await _node("100.00", "USD")
        await _node("250.50", "USD")
        await _node("80.00", "EUR")
        await _node(None, None)  # price-less node: ignored
        await _node("999.00", "USD", status=NodeStatus.discarded)  # excluded
        await _node("999.00", "USD", selected=False)  # deselected alt: excluded

        totals = await sum_node_costs(db_session, itinerary.id)
        assert totals == {"USD": Decimal("350.50"), "EUR": Decimal("80.00")}

        # Status filter narrows to the chosen lifecycle states only.
        booked_only = await sum_node_costs(db_session, itinerary.id, statuses=[NodeStatus.booked])
        assert booked_only == {}
    finally:
        await _cleanup(itinerary.id)
