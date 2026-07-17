"""Uniform anchors across fork/trunk + zone acquisition (doc/itin-time.md).

The "Forks and reconcile" decision, made real:

1. A fork inherits the trunk's timing block + anchors at creation (a branch
   starts at HEAD) — its cloned relative schedules mean the same dates.
2. A fork retime is legal (no fork/trunk asymmetry; world-pinned nodes hold
   everywhere) and surfaces at reconcile as a ``timing`` change — never as
   phantom per-node ``starts_at`` diffs on every card.
3. Reconcile re-derives ``starts_at`` against the DESTINATION's anchor when a
   schedule copies fork→trunk; the tstzrange is kernel output, never copied.
4. Publish folds the fork's anchor onto an anchorless trunk so Day-N identity
   survives.

Plus the "Zone acquisition" cascade in ``kernel_sync.derive_schedule``: sticky
real zone → location metadata (lat/lng → tzdb; flights per endpoint) → the
offset's pseudo-zone. The zone-cascade tests are pure (no DB); the fork tests
run against local Supabase and skip cleanly without it.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.kernel import PinnedSchedule, RelativeSchedule, resolve_schedule
from app.models import Itinerary, ItineraryTimingKind, NodeStatus, NodeType
from app.models.itinerary import Node
from app.services.fork import (
    ForkDiff,
    ReconcileDecision,
    ReconcileResult,
    diff_fork,
    fork_itinerary,
    reconcile_fork,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    RetimeResult,
    add_node,
    create_itinerary,
    get_itinerary_graph,
    retime_itinerary,
)
from app.services.kernel_sync import decoded_schedule, derive_schedule
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range
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
    return ActorContext(user_id=None, kind=kind, actor_id=f"fork-timing-{kind.value}")


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(*itinerary_ids: uuid.UUID | None) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                if iid is None:
                    continue
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(
                    text("delete from public.edge_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
    finally:
        await engine.dispose()


async def _dated_itinerary(session: AsyncSession, *, title: str) -> Any:
    return await create_itinerary(
        session,
        _actor(),
        title=title,
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
        date_end=date(2027, 8, 31),
        duration_nights=7,
    )


async def _scheduled_node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    starts_at: str,
    title: str = "Dinner",
) -> Any:
    node = await add_node(
        session,
        _actor(),
        itinerary_id=itinerary_id,
        type=NodeType.meal,
        status=NodeStatus.pending,
        title=title,
        starts_at=starts_at,
        duration_minutes=60,
    )
    assert not isinstance(node, ItineraryError)
    return node


async def _get_node(session: AsyncSession, node_id: uuid.UUID) -> Node:
    node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one()
    await session.refresh(node)
    return node


# ── 1. fork inherits timing at creation ──────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_fork_inherits_timing_block_and_anchor(db_session: AsyncSession) -> None:
    trunk = await _dated_itinerary(db_session, title="inherit")
    fork_id: uuid.UUID | None = None
    try:
        await _scheduled_node(db_session, trunk.id, starts_at="2027-06-02T09:00:00+02:00")
        await db_session.refresh(trunk)
        assert trunk.anchor_date is not None  # stamped by the schedule write

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=trunk.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        assert fork.timing_kind is trunk.timing_kind
        assert fork.date_start == trunk.date_start
        assert fork.date_end == trunk.date_end
        assert fork.duration_nights == trunk.duration_nights
        assert fork.days_anchor == trunk.days_anchor
        assert fork.anchor_date == trunk.anchor_date
    finally:
        await _cleanup(fork_id, trunk.id)


# ── 2. fork retime → timing change, no phantom node diffs ────────────────────


@integration
@pytest.mark.asyncio
async def test_fork_retime_surfaces_timing_change_not_node_diffs(
    db_session: AsyncSession,
) -> None:
    trunk = await _dated_itinerary(db_session, title="diverge")
    fork_id: uuid.UUID | None = None
    try:
        pinned = await retime_itinerary(db_session, _actor(), trunk, date_start=date(2027, 6, 1))
        assert isinstance(pinned, RetimeResult)
        node = await _scheduled_node(db_session, trunk.id, starts_at="2027-06-03T19:30:00+02:00")

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=trunk.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        # The traveler retimes THEIR fork — legal, no fork/trunk asymmetry.
        moved = await retime_itinerary(db_session, _actor(), fork, date_start=date(2027, 9, 10))
        assert isinstance(moved, RetimeResult)

        diff = await diff_fork(db_session, fork_id=fork.id)
        assert isinstance(diff, ForkDiff)

        # The whole-trip move is the timing change's to report…
        assert diff.timing is not None
        assert diff.timing.kind == "timing"
        assert diff.timing.change_id == fork.id
        assert "anchor_date" in diff.timing.fields
        assert "date_start" in diff.timing.fields
        assert diff.timing.before is not None and diff.timing.after is not None
        assert diff.timing.after["anchor_date"] == "2027-09-10"

        # …NOT a phantom per-node starts_at diff on every card: the node's
        # relative intent (Day 3, 19:30) never changed.
        assert diff.changed == []
        assert node.id not in {c.baseline_node_id for c in diff.changed}
    finally:
        await _cleanup(fork_id, trunk.id)


# ── 3. accepting the timing change retimes the trunk ─────────────────────────


@integration
@pytest.mark.asyncio
async def test_accepting_timing_adopts_fork_dates_and_rederives_trunk(
    db_session: AsyncSession,
) -> None:
    trunk = await _dated_itinerary(db_session, title="adopt")
    fork_id: uuid.UUID | None = None
    try:
        pinned = await retime_itinerary(db_session, _actor(), trunk, date_start=date(2027, 6, 1))
        assert isinstance(pinned, RetimeResult)
        node = await _scheduled_node(db_session, trunk.id, starts_at="2027-06-03T19:30:00+02:00")

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=trunk.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        moved = await retime_itinerary(db_session, _actor(), fork, date_start=date(2027, 9, 10))
        assert isinstance(moved, RetimeResult)

        result = await reconcile_fork(
            db_session, _actor(), fork_id=fork.id, decisions=[], accept_all=True
        )
        assert isinstance(result, ReconcileResult)
        timing_outcomes = [o for o in result.outcomes if o.kind == "timing"]
        assert len(timing_outcomes) == 1
        assert timing_outcomes[0].result == "applied"
        assert "moved=1" in (timing_outcomes[0].detail or "")

        await db_session.refresh(trunk)
        assert trunk.anchor_date == date(2027, 9, 10)
        assert trunk.date_start == date(2027, 9, 10)

        # The trunk node re-resolved against the adopted anchor: Day 3, 19:30
        # wall-clock preserved, and resolve(columns) == stored starts_at.
        fresh = await _get_node(db_session, node.id)
        assert fresh.metadata_["start_time"].startswith("2027-09-12T19:30:00")
        decoded = decoded_schedule(fresh)
        assert decoded is not None
        span = resolve_schedule(decoded, trunk.anchor_date)
        assert span is not None
        assert span.start == fresh.starts_at.lower
    finally:
        await _cleanup(fork_id, trunk.id)


# ── 4. declining the timing change keeps the trunk's dates ───────────────────


@integration
@pytest.mark.asyncio
async def test_declining_timing_keeps_trunk_dates(db_session: AsyncSession) -> None:
    trunk = await _dated_itinerary(db_session, title="decline")
    fork_id: uuid.UUID | None = None
    try:
        pinned = await retime_itinerary(db_session, _actor(), trunk, date_start=date(2027, 6, 1))
        assert isinstance(pinned, RetimeResult)
        node = await _scheduled_node(db_session, trunk.id, starts_at="2027-06-03T19:30:00+02:00")

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=trunk.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        moved = await retime_itinerary(db_session, _actor(), fork, date_start=date(2027, 9, 10))
        assert isinstance(moved, RetimeResult)

        result = await reconcile_fork(
            db_session,
            _actor(),
            fork_id=fork.id,
            decisions=[ReconcileDecision(change_id=fork.id, accept=False)],
        )
        assert isinstance(result, ReconcileResult)
        assert [o.result for o in result.outcomes if o.kind == "timing"] == ["discarded"]

        await db_session.refresh(trunk)
        assert trunk.anchor_date == date(2027, 6, 1)
        fresh = await _get_node(db_session, node.id)
        assert fresh.metadata_["start_time"].startswith("2027-06-03T19:30:00")
    finally:
        await _cleanup(fork_id, trunk.id)


# ── 5. publish folds the fork's anchor onto an anchorless trunk ──────────────


@integration
@pytest.mark.asyncio
async def test_publish_folds_anchor_onto_anchorless_trunk(db_session: AsyncSession) -> None:
    trunk = await create_itinerary(db_session, _actor(), title="empty-main")
    fork_id: uuid.UUID | None = None
    try:
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=trunk.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        # Solo traveler builds in the fork; the schedule write stamps ITS anchor.
        node = await _scheduled_node(
            db_session, fork.id, starts_at="2027-06-03T19:30:00+02:00", title="Fork dinner"
        )
        await db_session.refresh(fork)
        assert fork.anchor_date is not None
        assert trunk.anchor_date is None

        result = await reconcile_fork(
            db_session, _actor(), fork_id=fork.id, decisions=[], accept_all=True
        )
        assert isinstance(result, ReconcileResult)

        await db_session.refresh(trunk)
        assert trunk.anchor_date == fork.anchor_date  # Day-N identity survives

        # The copied node's schedule re-derived against the folded anchor:
        # canonical columns and the tstzrange agree on the trunk.
        tview = await get_itinerary_graph(db_session, trunk.id)
        assert not isinstance(tview, ItineraryError)
        copied = next(n for n in tview.nodes if n.title == "Fork dinner")
        fresh = await _get_node(db_session, copied.id)
        decoded = decoded_schedule(fresh)
        assert decoded is not None
        span = resolve_schedule(decoded, trunk.anchor_date)
        assert span is not None
        assert span.start == fresh.starts_at.lower
        assert span.start == (await _get_node(db_session, node.id)).starts_at.lower
    finally:
        await _cleanup(fork_id, trunk.id)


# ── zone acquisition cascade (pure — no DB) ──────────────────────────────────


def _mem_node(
    *,
    type_: NodeType = NodeType.experience,
    status: NodeStatus = NodeStatus.pending,
    metadata: dict[str, Any] | None = None,
    start_tz: str | None = None,
    start: datetime = datetime(2027, 6, 3, 17, 30, tzinfo=UTC),
) -> Node:
    return Node(
        itinerary_id=uuid.uuid4(),
        type=type_,
        status=status,
        title="mem",
        metadata_=metadata or {},
        starts_at=Range(start, start + timedelta(hours=1), bounds="[)"),
        start_tz=start_tz,
    )


ANCHOR = date(2027, 6, 1)


def test_location_zone_beats_pseudo_zone() -> None:
    node = _mem_node(
        metadata={
            "tz_offset_minutes": 120,
            "location": {"lat": 45.9852, "lng": 9.2572},  # Lake Como
        }
    )
    schedule = derive_schedule(node, ANCHOR)
    assert isinstance(schedule, RelativeSchedule)
    assert schedule.start.tz_name == "Europe/Rome"
    # Instant-exact: 17:30Z is 19:30 in Rome (CEST) — wall follows the zone.
    assert schedule.start.wall_time.hour == 19


def test_flight_zones_per_endpoint() -> None:
    node = _mem_node(
        type_=NodeType.flight,
        status=NodeStatus.booked,
        metadata={
            "tz_offset_minutes": -240,
            "from_location": {"lat": 42.2124, "lng": -83.3534},  # DTW
            "to_location": {"lat": 40.5197, "lng": 22.9709},  # SKG
        },
    )
    schedule = derive_schedule(node, ANCHOR)
    assert isinstance(schedule, PinnedSchedule)  # booked pins
    assert schedule.start.tz_name == "America/Detroit"
    assert schedule.end is not None
    assert schedule.end.tz_name == "Europe/Athens"


def test_sticky_real_zone_wins_over_location() -> None:
    node = _mem_node(
        start_tz="Europe/Paris",
        metadata={"location": {"lat": 45.9852, "lng": 9.2572}},
    )
    schedule = derive_schedule(node, ANCHOR)
    assert isinstance(schedule, RelativeSchedule)
    assert schedule.start.tz_name == "Europe/Paris"


def test_no_location_falls_back_to_pseudo_zone() -> None:
    node = _mem_node(metadata={"tz_offset_minutes": 120})
    schedule = derive_schedule(node, ANCHOR)
    assert isinstance(schedule, RelativeSchedule)
    assert schedule.start.tz_name == "Etc/GMT-2"


def test_ocean_location_falls_back_to_pseudo_zone() -> None:
    node = _mem_node(metadata={"tz_offset_minutes": 0, "location": {"lat": 0.0, "lng": 0.0}})
    schedule = derive_schedule(node, ANCHOR)
    assert isinstance(schedule, RelativeSchedule)
    assert schedule.start.tz_name == "Etc/GMT"
