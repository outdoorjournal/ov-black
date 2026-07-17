"""Phase 3 (doc/itin-time.md): the write path keeps the kernel columns fresh.

Every schedule-touching service write must leave the canonical 0055 columns
resolving to exactly the node's ``starts_at`` — the per-write version of the
Phase 2 dual-read gate — and the revalidation lifecycle must fire: moving a
quoted flight flags it, a fresh quote clears it, a retime reports it.
"""

from __future__ import annotations

import socket
import uuid
from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from app.kernel import resolve_schedule
from app.models import ItineraryTimingKind, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    RetimeResult,
    add_node,
    create_itinerary,
    retime_itinerary,
    update_node,
)
from app.services.kernel_sync import decoded_schedule
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 54322))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="kernel-phase3-test")


@pytest_asyncio.fixture
async def db_session() -> Any:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _cleanup(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    from sqlalchemy import text

    await session.execute(text("delete from itineraries where id = :iid"), {"iid": itinerary_id})
    await session.commit()


def _assert_dual_read(node: Any, anchor: date | None) -> None:
    """The per-node Phase 2 gate: canonical columns resolve to starts_at."""
    schedule = decoded_schedule(node)
    assert schedule is not None, "canonical columns missing after a service write"
    span = resolve_schedule(schedule, anchor)
    assert span is not None
    assert span.start == node.starts_at.lower
    assert span.end == node.starts_at.upper


@integration
async def test_add_node_writes_canonical_columns(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase3-add",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
        date_end=date(2027, 6, 20),
    )
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.meal,
            title="Dinner",
            starts_at="2027-06-03T20:00:00+02:00",
            duration_minutes=90,
        )
        assert not isinstance(node, ItineraryError)
        await db_session.refresh(node)
        await db_session.refresh(itin)
        assert itin.anchor_date == date(2027, 6, 1)  # stamped with days_anchor
        assert node.schedule_kind == "relative"
        assert node.start_day_offset == 2  # Jun 3 = Day 3
        assert str(node.start_wall_time) == "20:00:00"
        _assert_dual_read(node, itin.anchor_date)
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_flight_revalidation_lifecycle(db_session: AsyncSession) -> None:
    """Move a quoted flight → flagged; re-quote (new source_id) → cleared."""
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase3-flight",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        flight = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.flight,
            title="DTW → SKG",
            source="duffel",
            source_id="off_1",
            starts_at="2027-06-01T10:00:00-04:00",
            duration_minutes=600,
        )
        assert not isinstance(flight, ItineraryError)
        assert flight.needs_revalidation is False  # first placement of the quote

        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=flight.id,
            metadata={
                **flight.metadata_,
                "start_time": "2027-06-05T10:00:00-04:00",
            },
        )
        assert not isinstance(moved, ItineraryError)
        assert moved.needs_revalidation is True  # the quote no longer matches its date

        requoted = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=flight.id,
            source_id="off_2",
        )
        assert not isinstance(requoted, ItineraryError)
        assert requoted.needs_revalidation is False  # fresh quote clears the flag
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_retime_reports_moved_flights_as_stale(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase3-retime-stale",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        flight = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.flight,
            title="Quoted flight",
            source="duffel",
            source_id="off_1",
            starts_at="2027-06-01T10:00:00-04:00",
            duration_minutes=600,
        )
        meal = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.meal,
            title="Dinner",
            starts_at="2027-06-02T20:00:00+02:00",
        )
        assert not isinstance(flight, ItineraryError)
        assert not isinstance(meal, ItineraryError)

        result = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 7, 1))
        assert isinstance(result, RetimeResult)
        assert set(result.shifted_node_ids) == {flight.id, meal.id}
        assert result.stale_node_ids == (flight.id,)  # only the quote is date-sensitive
        assert result.held_node_ids == ()

        await db_session.refresh(flight)
        await db_session.refresh(meal)
        assert flight.needs_revalidation is True
        assert meal.needs_revalidation is False
        # The wall-clock promises survived the move (Day 1 10:00 / Day 2 20:00).
        assert flight.metadata_["start_time"].startswith("2027-07-01T10:00:00")
        assert meal.metadata_["start_time"].startswith("2027-07-02T20:00:00")
        await db_session.refresh(itin)
        _assert_dual_read(flight, itin.anchor_date)
        _assert_dual_read(meal, itin.anchor_date)
    finally:
        await _cleanup(db_session, itin.id)
