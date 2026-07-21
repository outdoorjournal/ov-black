"""The Olympus spine × the kernel time contract — the scenarios that kept
breaking while the demo was being built.

The trip is placed the way the campaign dashboard places it — often with NO
dates chosen yet — and dates arrive later ("August 1st, 2026") as a retime.
Every state along that path must hold two properties:

* the kernel analysis actually SEES the spine (each scheduled card carries a
  canonical relative schedule, so an undated trip analyzes on its provisional
  calendar instead of being vacuously clean), and
* the analysis runs CLEAN — laying down our own curated template and then
  pinning dates must never manufacture findings (the historical offender: the
  cornerstone anchor's whole-days span bleeding into the extension's first
  morning as a phantom overlap).

Real-DB integration (like ``test_olympus_template``): skipped unless the local
Supabase Postgres is reachable.
"""

from __future__ import annotations

import socket
import uuid
from datetime import date, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from app.kernel import RelativeSchedule, analyze
from app.models import ItineraryTimingKind
from app.routers.itineraries import (
    _itinerary_trip_start,
    _kernel_read_for_view,
    _template_tz,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    GraphView,
    Itinerary,
    RetimeResult,
    create_itinerary,
    get_itinerary_graph,
    retime_itinerary,
)
from app.services.kernel_graph import kernel_graph_from_view
from app.services.olympus_template import build_olympus_template
from app.services.templates import instantiate_into
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"

NIGHTS = 14
AUG_1 = date(2026, 8, 1)


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
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="olympus-time-test")


@pytest_asyncio.fixture
async def db_session() -> Any:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _cleanup(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    await session.execute(text("delete from itineraries where id = :iid"), {"iid": itinerary_id})
    await session.commit()


async def _kickoff(
    session: AsyncSession,
    *,
    timing_kind: ItineraryTimingKind,
    date_start: date | None = None,
) -> Itinerary:
    """Lay the 14-night spine down the way ``campaign_kickoff_endpoint`` does:
    build the template, anchor at the trip's declared start (or the provisional
    ~30-days-out fallback), pin only when the traveler chose exact dates."""
    itin = await create_itinerary(
        session,
        _actor(),
        title="olympus-time-scenario",
        timing_kind=timing_kind,
        date_start=date_start,
        duration_nights=NIGHTS,
    )
    template = await build_olympus_template(session, nights=NIGHTS)
    trip_start_at = _itinerary_trip_start(itin, _template_tz(template))
    pin = timing_kind is ItineraryTimingKind.exact and date_start is not None
    await instantiate_into(
        session, template=template, itinerary=itin, trip_start_at=trip_start_at, pin=pin
    )
    return itin


async def _graph(session: AsyncSession, itinerary_id: uuid.UUID) -> GraphView:
    view = await get_itinerary_graph(session, itinerary_id)
    assert isinstance(view, GraphView)
    return view


def _scheduled_roots(view: GraphView) -> list[Any]:
    return [
        n
        for n in view.nodes
        if n.parent_subgraph_id is None and n.attached_to_node_id is None and n.starts_at
    ]


def _assert_analysis_sees_the_spine(view: GraphView) -> None:
    """Guard against vacuous cleanliness: every scheduled spine card must carry
    a canonical relative schedule the kernel can actually judge."""
    roots = _scheduled_roots(view)
    assert roots, "the spine instantiated no scheduled cards"
    for n in roots:
        assert isinstance(n.kernel_schedule, RelativeSchedule), (
            f"{n.title!r} has no canonical schedule — the analysis cannot see it"
        )
        assert n.schedule is not None, f"{n.title!r} serializes no resolved schedule view"


def _assert_clean(view: GraphView) -> None:
    findings = analyze(kernel_graph_from_view(view))
    assert findings == (), [f"{f.severity}/{f.code}: {f.message}" for f in findings]
    # And the router's serialization of the same judgement.
    responses, _nights = _kernel_read_for_view(view)
    assert responses == []


def _day_indexes(view: GraphView) -> dict[str, int]:
    return {n.title: n.schedule.start.day_index for n in _scheduled_roots(view)}


@integration
async def test_spine_without_dates_analyzes_clean(db_session: AsyncSession) -> None:
    """Place the 14-night Olympus trip with NO dates chosen: the spine lays out
    as stable Day-N slots, the trip stays unpinned, and the provisional-calendar
    analysis is clean — meaningfully, not for lack of schedules."""
    itin = await _kickoff(db_session, timing_kind=ItineraryTimingKind.window)
    try:
        view = await _graph(db_session, itin.id)

        # The kickoff must not invent calendar dates the traveler never gave.
        assert view.itinerary.timing_kind is ItineraryTimingKind.window
        assert view.itinerary.date_start is None
        assert view.itinerary.anchor_date is not None, "kernel anchor stamps provisionally"

        _assert_analysis_sees_the_spine(view)
        _assert_clean(view)

        # The composition reads Day 1 (travel) → Day 2 (ascent) → … → Day 14.
        days = _day_indexes(view)
        assert days["Travel day — held for your arrival"] == 1
        assert days["Trip to Mount Olympus — The Path to Symbolism"] == 2
        assert days["Recovery day — Olympian Riviera"] == 8
        assert max(days.values()) == NIGHTS
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_adding_dates_later_resolves_and_analyzes_clean(db_session: AsyncSession) -> None:
    """The struggle scenario: place without dates, then the traveler settles on
    Aug 1 2026. The retime re-resolves every card (nothing held, nothing stale),
    Day N becomes a real date with its wall clock intact, and the analysis on
    the pinned graph is clean."""
    itin = await _kickoff(db_session, timing_kind=ItineraryTimingKind.window)
    try:
        undated = _day_indexes(await _graph(db_session, itin.id))

        result = await retime_itinerary(db_session, _actor(), itin, date_start=AUG_1)
        assert isinstance(result, RetimeResult)
        assert result.held_node_ids == ()
        assert result.stale_node_ids == ()

        view = await _graph(db_session, itin.id)
        assert view.itinerary.timing_kind is ItineraryTimingKind.exact
        assert view.itinerary.date_start == AUG_1
        assert view.itinerary.date_end == date(2026, 8, 15)  # 14 nights
        assert view.itinerary.anchor_date == AUG_1

        _assert_analysis_sees_the_spine(view)
        _assert_clean(view)

        # Day N survived the pin exactly — same relative structure...
        assert _day_indexes(view) == undated

        # ...and now resolves onto the real calendar in the trip's real zone.
        by_title = {n.title: n for n in _scheduled_roots(view)}
        travel = by_title["Travel day — held for your arrival"].schedule.start
        assert travel.on == AUG_1
        assert travel.wall_time == time(9, 0)
        ascent = by_title["Trip to Mount Olympus — The Path to Symbolism"].schedule.start
        assert ascent.on == date(2026, 8, 2)
        assert ascent.wall_time == time(15, 0)
        assert ascent.instant == ascent.instant.astimezone(ZoneInfo(ascent.tz_name))
        assert ascent.instant.utcoffset() is not None

        # Every card lands inside the trip frame [Aug 1, Aug 15).
        for n in _scheduled_roots(view):
            assert AUG_1 <= n.schedule.start.on < date(2026, 8, 15), n.title
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_spine_with_exact_dates_up_front_analyzes_clean(db_session: AsyncSession) -> None:
    """The sibling path: the traveler chose Aug 1 before kickoff, so the spine
    is born pinned — and must be exactly as clean as the retimed one."""
    itin = await _kickoff(db_session, timing_kind=ItineraryTimingKind.exact, date_start=AUG_1)
    try:
        view = await _graph(db_session, itin.id)
        assert view.itinerary.timing_kind is ItineraryTimingKind.exact
        assert view.itinerary.date_start == AUG_1
        assert view.itinerary.anchor_date == AUG_1

        _assert_analysis_sees_the_spine(view)
        _assert_clean(view)

        by_title = {n.title: n for n in _scheduled_roots(view)}
        assert by_title["Travel day — held for your arrival"].schedule.start.on == AUG_1
        assert by_title["A slow day in the villages"].schedule.start.on == date(2026, 8, 14)
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_moving_dates_again_keeps_wall_clocks_and_stays_clean(
    db_session: AsyncSession,
) -> None:
    """Retime a second time (Aug 1 → Sep 1): the historical drift bug was the
    parse-shift-rewrite loop corrupting wall clocks on repeat moves. Relative
    schedules never change; only their resolution does."""
    itin = await _kickoff(db_session, timing_kind=ItineraryTimingKind.window)
    try:
        await retime_itinerary(db_session, _actor(), itin, date_start=AUG_1)
        first = await _graph(db_session, itin.id)
        walls_before = {
            n.title: (n.schedule.start.day_index, n.schedule.start.wall_time)
            for n in _scheduled_roots(first)
        }

        sep_1 = date(2026, 9, 1)
        result = await retime_itinerary(db_session, _actor(), itin, date_start=sep_1)
        assert isinstance(result, RetimeResult)
        assert result.delta_days == 31
        assert result.held_node_ids == ()

        view = await _graph(db_session, itin.id)
        assert view.itinerary.anchor_date == sep_1
        _assert_analysis_sees_the_spine(view)
        _assert_clean(view)

        walls_after = {
            n.title: (n.schedule.start.day_index, n.schedule.start.wall_time)
            for n in _scheduled_roots(view)
        }
        assert walls_after == walls_before
        travel = next(
            n for n in _scheduled_roots(view) if n.title == "Travel day — held for your arrival"
        )
        assert travel.schedule.start.on == sep_1

        # A pinned spine that only note/free_time/experience cards make up
        # never holds or stales — the seed ships no supplier commitments, so
        # date moves stay frictionless until something is actually booked.
        for n in _scheduled_roots(view):
            assert n.needs_revalidation is False, n.title
    finally:
        await _cleanup(db_session, itin.id)
