"""Phase 4 (doc/itin-time.md): reads return resolved time; placements are trip-terms.

Two halves:

* Pure kernel — ``resolve_view`` projects a schedule into the display shape
  (day_index / local date / wall time / zone / instant, per endpoint), and the
  placement helpers (``trip_default_zone`` / ``follows_order`` /
  ``synthesize_placements``) reproduce the web adapter's retired synthesis
  rule as one kernel computation.
* Integration — ``update_node(placement=…)`` builds the schedule from a
  ``(day_index, minute_of_day)`` drop through the kernel (real IANA zones
  enter here and stay sticky across legacy writes), ``clear_schedule``
  returns a card to the Collection, and ``get_itinerary_graph`` serializes a
  resolved view per node, synthesized slots included.
"""

from __future__ import annotations

import socket
import uuid
from datetime import date, time
from typing import Any

import pytest
import pytest_asyncio
from app.kernel import (
    AbsoluteStamp,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    follows_order,
    relative,
    resolve_schedule,
    resolve_view,
    synthesize_placements,
    trip_default_zone,
)
from app.models import ItineraryTimingKind, NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    GraphView,
    ItineraryError,
    SchedulePlacement,
    add_node,
    create_itinerary,
    get_itinerary_graph,
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


# ── resolve_view (pure) ─────────────────────────────────────────────────────


def test_resolve_view_relative_anchored() -> None:
    view = resolve_view(
        relative(3, time(9, 0), "Europe/Athens", duration_minutes=90),
        anchor=date(2026, 8, 1),
    )
    assert view.kind == "relative"
    assert view.start.day_index == 3
    assert view.start.on == date(2026, 8, 3)
    assert view.start.wall_time == time(9, 0)
    assert view.start.tz_name == "Europe/Athens"
    assert view.start.instant is not None
    assert view.start.instant.isoformat() == "2026-08-03T09:00:00+03:00"
    assert view.end is not None
    assert view.end.wall_time == time(10, 30)
    assert view.day_span == 1


def test_resolve_view_relative_undated_has_day_but_no_date() -> None:
    view = resolve_view(relative(4, time(14, 0), "Asia/Tokyo"), anchor=None)
    assert view.start.day_index == 4
    assert view.start.on is None
    assert view.start.instant is None
    assert view.start.wall_time == time(14, 0)


def test_resolve_view_relative_midnight_rollover_spans_two_days() -> None:
    view = resolve_view(
        relative(2, time(23, 0), "UTC", duration_minutes=120),
        anchor=date(2026, 8, 1),
    )
    assert view.end is not None
    assert view.end.day_index == 3
    assert view.day_span == 2


def test_resolve_view_pinned_cross_zone_flight() -> None:
    """A Detroit→Athens overnight: each endpoint in its own zone, +1 day."""
    schedule = PinnedSchedule(
        start=AbsoluteStamp(on=date(2026, 8, 6), wall_time=time(17, 45), tz_name="America/Detroit"),
        end=AbsoluteStamp(on=date(2026, 8, 7), wall_time=time(10, 20), tz_name="Europe/Athens"),
    )
    view = resolve_view(schedule, anchor=date(2026, 8, 6))
    assert view.kind == "pinned"
    assert view.start.day_index == 1
    assert view.end is not None
    assert view.end.day_index == 2
    assert view.end.tz_name == "Europe/Athens"
    assert view.day_span == 2
    assert view.start.instant is not None and view.end.instant is not None
    assert view.end.instant > view.start.instant  # true instants, not string order


def test_resolve_view_pinned_undated_has_date_but_no_day() -> None:
    schedule = PinnedSchedule(
        start=AbsoluteStamp(on=date(2026, 12, 31), wall_time=time(21, 0), tz_name="Europe/Paris")
    )
    view = resolve_view(schedule, anchor=None)
    assert view.start.day_index is None
    assert view.start.on == date(2026, 12, 31)
    assert view.start.instant is not None


# ── placement helpers (pure) ────────────────────────────────────────────────


def test_trip_default_zone_majority_and_tiebreak() -> None:
    assert trip_default_zone(["Asia/Tokyo", "Asia/Tokyo", "UTC"]) == "Asia/Tokyo"
    # Tie → deterministic (alphabetical) winner.
    assert trip_default_zone(["Europe/Paris", "Europe/Athens"]) == "Europe/Athens"
    assert trip_default_zone([]) == "UTC"
    assert trip_default_zone([None, None]) == "UTC"


def test_follows_order_chains_then_orphans() -> None:
    ids = ["c", "a", "b", "x"]
    edges = [("a", "b"), ("b", "c")]
    assert follows_order(ids, edges) == ["a", "b", "c", "x"]


def test_follows_order_cycle_falls_back_to_input_order() -> None:
    ids = ["a", "b"]
    edges = [("a", "b"), ("b", "a")]
    assert follows_order(ids, edges) == ["a", "b"]


def test_synthesize_placements_steps_and_rolls_days() -> None:
    ids = [f"n{i}" for i in range(16)]
    placements = synthesize_placements(ids, "Europe/Athens")
    first = placements["n0"]
    assert first.start.day_offset == 0
    assert first.start.wall_time == time(9, 0)
    assert first.start.tz_name == "Europe/Athens"
    assert placements["n5"].start.wall_time == time(14, 0)
    # 9:00 + 15h steps crosses midnight onto Day 2.
    assert placements["n15"].start.day_offset == 1
    assert placements["n15"].start.wall_time == time(0, 0)


# ── integration: placement writes + resolved reads ──────────────────────────


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="kernel-phase4-test")


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


@integration
async def test_placement_builds_schedule_through_kernel(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-placement",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
        date_end=date(2027, 6, 20),
    )
    try:
        node = await add_node(
            db_session, _actor(), itinerary_id=itin.id, type=NodeType.experience, title="Hike"
        )
        assert not isinstance(node, ItineraryError)
        assert node.starts_at is None  # born in the Collection

        placed = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            placement=SchedulePlacement(
                day_index=3,
                minute_of_day=10 * 60 + 30,
                duration_minutes=120,
                tz_name="Europe/Athens",
            ),
        )
        assert not isinstance(placed, ItineraryError)
        await db_session.refresh(placed)
        await db_session.refresh(itin)

        # Real IANA zone entered via the placement; canonical columns written
        # first-hand by the kernel.
        assert placed.schedule_kind == "relative"
        assert placed.start_day_offset == 2
        assert str(placed.start_wall_time) == "10:30:00"
        assert placed.start_tz == "Europe/Athens"
        assert placed.end_tz == "Europe/Athens"

        # starts_at is derived output and dual-reads exactly.
        schedule = decoded_schedule(placed)
        assert schedule is not None
        span = resolve_schedule(schedule, itin.anchor_date)
        assert span is not None
        assert span.start == placed.starts_at.lower
        assert span.end == placed.starts_at.upper

        # Read-compat mirrors carry the promised wall clock in the real zone.
        assert placed.metadata_["start_time"] == "2027-06-03T10:30:00+03:00"
        assert placed.metadata_["tz_offset_minutes"] == 180
        assert placed.metadata_["duration_minutes"] == 120
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_placement_stamps_anchor_on_undated_trip(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="phase4-undated")
    try:
        node = await add_node(
            db_session, _actor(), itinerary_id=itin.id, type=NodeType.meal, title="Dinner"
        )
        assert not isinstance(node, ItineraryError)
        placed = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            placement=SchedulePlacement(day_index=1, minute_of_day=20 * 60),
        )
        assert not isinstance(placed, ItineraryError)
        await db_session.refresh(itin)
        assert itin.anchor_date is not None  # the first placement pinned Day 1's identity
        assert placed.start_day_offset == 0
        assert placed.starts_at is not None
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_placement_keeps_node_zone_and_flags_flight_quotes(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-flight",
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
        assert flight.needs_revalidation is False

        # No tz on the drop → the node's current zone is kept.
        prior_zone = flight.start_tz
        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=flight.id,
            placement=SchedulePlacement(day_index=5, minute_of_day=10 * 60),
        )
        assert not isinstance(moved, ItineraryError)
        assert moved.start_tz == prior_zone
        assert moved.start_day_offset == 4
        assert moved.needs_revalidation is True  # the quote no longer matches its date
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_real_zone_is_sticky_across_legacy_writes(db_session: AsyncSession) -> None:
    """A real IANA zone written by a placement survives a metadata ISO write."""
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-sticky",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        node = await add_node(
            db_session, _actor(), itinerary_id=itin.id, type=NodeType.experience, title="Sail"
        )
        assert not isinstance(node, ItineraryError)
        placed = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            placement=SchedulePlacement(day_index=2, minute_of_day=9 * 60, tz_name="Europe/Athens"),
        )
        assert not isinstance(placed, ItineraryError)

        # Legacy write path (agent tools still speak ISO-with-offset).
        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            metadata={**placed.metadata_, "start_time": "2027-06-04T11:00:00+03:00"},
        )
        assert not isinstance(moved, ItineraryError)
        assert moved.start_tz == "Europe/Athens"  # not clobbered back to Etc/GMT-3
        assert moved.start_day_offset == 3
        assert str(moved.start_wall_time) == "11:00:00"
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_clear_schedule_returns_card_to_collection(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-clear",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Maybe later",
            starts_at="2027-06-02T10:00:00+03:00",
            duration_minutes=60,
        )
        assert not isinstance(node, ItineraryError)
        cleared = await update_node(
            db_session, _actor(), itinerary_id=itin.id, node_id=node.id, clear_schedule=True
        )
        assert not isinstance(cleared, ItineraryError)
        assert cleared.starts_at is None
        assert cleared.schedule_kind is None
        assert cleared.start_tz is None
        assert "start_time" not in cleared.metadata_
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_graph_read_serializes_resolved_and_synthesized_views(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-read",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        meal = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.meal,
            title="Dinner",
            starts_at="2027-06-03T20:00:00+02:00",
            duration_minutes=90,
        )
        wish = await add_node(
            db_session, _actor(), itinerary_id=itin.id, type=NodeType.experience, title="Wish"
        )
        assert not isinstance(meal, ItineraryError)
        assert not isinstance(wish, ItineraryError)

        view = await get_itinerary_graph(db_session, itin.id)
        assert isinstance(view, GraphView)
        by_id = {n.id: n for n in view.nodes}

        scheduled = by_id[meal.id]
        assert scheduled.schedule is not None
        assert scheduled.schedule_synthesized is False
        assert scheduled.schedule.kind == "relative"
        assert scheduled.schedule.start.day_index == 3
        assert scheduled.schedule.start.on == date(2027, 6, 3)
        assert scheduled.schedule.start.wall_time == time(20, 0)
        assert scheduled.schedule.start.instant is not None
        assert scheduled.schedule.start.instant.isoformat() == scheduled.starts_at

        collection = by_id[wish.id]
        assert collection.starts_at is None  # still unscheduled…
        assert collection.schedule is not None  # …but carries a provisional slot
        assert collection.schedule_synthesized is True
        assert collection.schedule.start.day_index == 1
        assert collection.schedule.start.wall_time == time(9, 0)
        # Synth zone follows the trip's scheduled nodes (Etc pseudo-zone until
        # real-zone writes reach this trip).
        assert collection.schedule.start.tz_name == scheduled.schedule.start.tz_name
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_discarded_and_attached_notes_get_no_synth_slot(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase4-no-synth",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
    )
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Host",
            starts_at="2027-06-02T10:00:00+03:00",
        )
        assert not isinstance(host, ItineraryError)
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.note,
            title="Attached note",
            attached_to_node_id=host.id,
        )
        discarded = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Discarded",
            status=NodeStatus.discarded,
        )
        assert not isinstance(note, ItineraryError)
        assert not isinstance(discarded, ItineraryError)

        view = await get_itinerary_graph(db_session, itin.id)
        assert isinstance(view, GraphView)
        by_id = {n.id: n for n in view.nodes}
        assert by_id[note.id].schedule is None
        assert by_id[discarded.id].schedule is None
    finally:
        await _cleanup(db_session, itin.id)


# ── relative schedule sanity used by the suite above ────────────────────────


def test_relative_stamp_negative_day_offset_is_legal() -> None:
    schedule = RelativeSchedule(
        start=RelativeStamp(day_offset=-1, wall_time=time(17, 0), tz_name="America/Detroit")
    )
    view = resolve_view(schedule, anchor=date(2026, 8, 1))
    assert view.start.day_index == 0  # the day before Day 1
    assert view.start.on == date(2026, 7, 31)
