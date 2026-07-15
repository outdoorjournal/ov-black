"""Relative days → pinned dates (Wave E: ADV-16 anchor + ADV-17 retime).

Integration tests against a local Supabase Postgres, mirroring
``test_bookings.py``'s harness:

- ``days_anchor`` stamping — the first scheduled card pins Day 1's identity
  (window ``date_start``, else the current UTC date) and it never re-stamps.
- ``retime_itinerary`` — shifts every scheduled node by ``date_start −
  days_anchor`` whole days preserving wall-clock + tz offset, flips the trip to
  ``exact``, re-stamps the anchor, writes node_history; refused while
  booked/confirmed cards exist.
- The symmetric loosen path — ``update_itinerary_details`` exact → window moves
  nothing and keeps the anchor (so labels flip back to Day-N coherently), and
  refuses while booked cards exist (``booked_dates_locked``).

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import ItineraryTimingKind, NodeHistory, NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    RetimeResult,
    add_node,
    create_itinerary,
    retime_itinerary,
    update_itinerary_details,
    update_node,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"rt-{kind.value}")


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


async def _windowed_itinerary(session: AsyncSession, *, title: str) -> Any:
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
    duration_minutes: int | None = 60,
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
        duration_minutes=duration_minutes,
    )
    assert not isinstance(node, ItineraryError)
    return node


# ── ADV-16: the anchor stamp ─────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_first_scheduled_card_stamps_window_start_as_anchor(
    db_session: AsyncSession,
) -> None:
    itin = await _windowed_itinerary(db_session, title="anchor-window")
    try:
        assert itin.days_anchor is None
        await _scheduled_node(db_session, itin.id, starts_at="2027-06-03T09:00:00+02:00")
        await db_session.refresh(itin)
        assert itin.days_anchor == date(2027, 6, 1)  # the window's date_start

        # Second scheduled card does NOT re-stamp.
        await _scheduled_node(db_session, itin.id, starts_at="2027-06-05T19:00:00+02:00")
        await db_session.refresh(itin)
        assert itin.days_anchor == date(2027, 6, 1)
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_first_scheduled_card_on_flexible_trip_stamps_today(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="anchor-flexible",
        timing_kind=ItineraryTimingKind.flexible,
    )
    try:
        await _scheduled_node(db_session, itin.id, starts_at="2027-06-03T09:00:00+02:00")
        await db_session.refresh(itin)
        assert itin.days_anchor == datetime.now(UTC).date()
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_drag_to_timeline_metadata_patch_stamps_anchor(
    db_session: AsyncSession,
) -> None:
    """The web's drag-from-Collection path (a metadata patch) stamps too."""
    itin = await _windowed_itinerary(db_session, title="anchor-drag")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            status=NodeStatus.pending,
            title="Unscheduled idea",
        )
        assert not isinstance(node, ItineraryError)
        await db_session.refresh(itin)
        assert itin.days_anchor is None  # nothing scheduled yet

        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=node.id,
            metadata={**node.metadata_, "start_time": "2027-06-02T10:00:00+02:00"},
        )
        assert not isinstance(moved, ItineraryError)
        await db_session.refresh(itin)
        assert itin.days_anchor == date(2027, 6, 1)
    finally:
        await _cleanup(itin.id)


# ── ADV-17: retime — the pinning gesture ─────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_retime_shifts_scheduled_nodes_preserving_wall_clock(
    db_session: AsyncSession,
) -> None:
    itin = await _windowed_itinerary(db_session, title="retime-shift")
    try:
        # Day 3 dinner + Day 1 check-in, both in a +02:00 zone; one unscheduled idea.
        checkin = await _scheduled_node(
            db_session, itin.id, starts_at="2027-06-01T15:00:00+02:00", title="Check-in"
        )
        dinner = await _scheduled_node(
            db_session, itin.id, starts_at="2027-06-03T19:30:00+02:00", title="Dinner"
        )
        idea = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="Maybe a boat",
        )
        assert not isinstance(idea, ItineraryError)

        # Pin Day 1 (= Jun 1 anchor) to Mar 18, 2027: a -75 day shift.
        result = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 3, 18))
        assert isinstance(result, RetimeResult)
        assert result.delta_days == (date(2027, 3, 18) - date(2027, 6, 1)).days
        assert set(result.shifted_node_ids) == {checkin.id, dinner.id}

        await db_session.refresh(itin)
        assert itin.timing_kind is ItineraryTimingKind.exact
        assert itin.date_start == date(2027, 3, 18)
        # duration_nights=7 counts the end forward from the new start.
        assert itin.date_end == date(2027, 3, 25)
        assert itin.days_anchor == date(2027, 3, 18)

        # Wall-clock + tz offset preserved; Day-1/Day-3 structure intact.
        await db_session.refresh(checkin)
        await db_session.refresh(dinner)
        assert checkin.metadata_["start_time"] == "2027-03-18T15:00:00+02:00"
        assert dinner.metadata_["start_time"] == "2027-03-20T19:30:00+02:00"

        # Each shifted node wrote a history row for the move.
        ops = (
            (
                await db_session.execute(
                    select(NodeHistory.node_id).where(
                        NodeHistory.itinerary_id == itin.id, NodeHistory.op == "update"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {checkin.id, dinner.id} <= set(ops)
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_retime_refused_while_booked_cards_exist(db_session: AsyncSession) -> None:
    itin = await _windowed_itinerary(db_session, title="retime-booked")
    try:
        node = await _scheduled_node(db_session, itin.id, starts_at="2027-06-02T09:00:00+02:00")
        # Simulate a booked card directly (the booking flow itself is pin-gated).
        node.status = NodeStatus.booked
        await db_session.commit()

        refused = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 7, 1))
        assert isinstance(refused, ItineraryError)
        assert refused.detail == "booked_dates_locked"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_loosen_keeps_anchor_and_cards_then_repin_shifts_again(
    db_session: AsyncSession,
) -> None:
    """The symmetric round-trip: pin → loosen (nothing moves) → re-pin (uniform shift)."""
    itin = await _windowed_itinerary(db_session, title="retime-roundtrip")
    try:
        node = await _scheduled_node(db_session, itin.id, starts_at="2027-06-02T09:00:00+02:00")
        pinned = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 3, 18))
        assert isinstance(pinned, RetimeResult)
        await db_session.refresh(node)
        assert node.metadata_["start_time"] == "2027-03-19T09:00:00+02:00"  # Day 2

        # Loosen back to a window: cards stay put, the anchor is kept.
        loosened = await update_itinerary_details(
            db_session,
            _actor(),
            itin,
            fields={
                "timing_kind": ItineraryTimingKind.window,
                "date_start": date(2027, 9, 1),
                "date_end": date(2027, 11, 30),
            },
        )
        assert not isinstance(loosened, ItineraryError)
        await db_session.refresh(node)
        assert node.metadata_["start_time"] == "2027-03-19T09:00:00+02:00"
        assert itin.days_anchor == date(2027, 3, 18)

        # Re-pin: another uniform shift from the KEPT anchor.
        repinned = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 10, 4))
        assert isinstance(repinned, RetimeResult)
        await db_session.refresh(node)
        assert node.metadata_["start_time"] == "2027-10-05T09:00:00+02:00"  # still Day 2
        assert itin.days_anchor == date(2027, 10, 4)
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_pinning_via_details_restamps_anchor_to_date_start(
    db_session: AsyncSession,
) -> None:
    """Pinning through the window-edit path re-stamps days_anchor = date_start.

    Regression: a card scheduled before dates were set stamps days_anchor at the
    then-current window start; later pinning the trip via update_itinerary_details
    left that stale anchor in place, so Day-N numbering counted from a phantom
    start (the "real Day 1 is now Day 8" bug) and a subsequent retime mis-shifted.
    """
    itin = await _windowed_itinerary(db_session, title="pin-via-details")
    try:
        # A Day-3 card (window start 2027-06-01 = Day 1).
        card = await _scheduled_node(db_session, itin.id, starts_at="2027-06-03T09:00:00+02:00")
        await db_session.refresh(itin)
        assert itin.days_anchor == date(2027, 6, 1)  # window start, stamped early

        pinned = await update_itinerary_details(
            db_session,
            _actor(),
            itin,
            fields={
                "timing_kind": ItineraryTimingKind.exact,
                "date_start": date(2027, 6, 10),
                "date_end": date(2027, 6, 20),
            },
        )
        assert not isinstance(pinned, ItineraryError)
        await db_session.refresh(itin)
        # The anchor follows date_start — Day 1 is the pinned start, not the
        # stale 2027-06-01 that would push the trip nine days out.
        assert itin.days_anchor == date(2027, 6, 10)
        # And the scheduled card moves WITH the anchor (+9 days), so it stays
        # Day 3 (2027-06-12) instead of being stranded before the new Day 1 —
        # the split-anchor bug the bare re-stamp used to leave behind.
        await db_session.refresh(card)
        assert card.metadata_["start_time"] == "2027-06-12T09:00:00+02:00"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_settling_exact_dates_shifts_provisional_anchor_spine(
    db_session: AsyncSession,
) -> None:
    """Settling exact dates retimes a spine laid at a provisional anchor.

    Regression (the Olympus split-anchor): a campaign spine is instantiated
    UNPINNED against a provisional ``days_anchor`` before the traveler settles
    dates. When intake then calls ``update_itinerary_details`` to pin exact
    dates, the already-scheduled cards must shift onto the new anchor — not just
    the anchor label. Otherwise the spine stays stranded at the provisional
    dates and the timeline renders Day 1 three days early.
    """
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="settle-provisional-spine",
        timing_kind=ItineraryTimingKind.flexible,
    )
    try:
        # Spine laid before dates are known: the first card stamps a provisional
        # anchor (today, on a flexible trip). Simulate the kickoff's Day 1 + Day 4.
        anchor = datetime.now(UTC).date()
        day1 = await _scheduled_node(
            db_session,
            itin.id,
            starts_at=f"{anchor.isoformat()}T15:00:00+03:00",
            title="Ascent begins",
        )
        day4 = await _scheduled_node(
            db_session,
            itin.id,
            starts_at=f"{(anchor + timedelta(days=3)).isoformat()}T11:00:00+03:00",
            title="Recovery day",
        )
        await db_session.refresh(itin)
        assert itin.days_anchor == anchor

        # Intake settles exact dates three days out from the provisional anchor.
        new_start = anchor + timedelta(days=3)
        settled = await update_itinerary_details(
            db_session,
            _actor(),
            itin,
            fields={
                "timing_kind": ItineraryTimingKind.exact,
                "date_start": new_start,
                "date_end": new_start + timedelta(days=14),
            },
        )
        assert not isinstance(settled, ItineraryError)
        await db_session.refresh(itin)
        assert itin.days_anchor == new_start
        assert itin.date_start == new_start

        # Both cards shifted +3 days, wall-clock preserved: Day 1 lands on the
        # settled start, Day 4 stays three days in.
        await db_session.refresh(day1)
        await db_session.refresh(day4)
        assert day1.metadata_["start_time"] == f"{new_start.isoformat()}T15:00:00+03:00"
        assert (
            day4.metadata_["start_time"]
            == f"{(new_start + timedelta(days=3)).isoformat()}T11:00:00+03:00"
        )
        # The move is audited, same as a retime.
        ops = (
            (
                await db_session.execute(
                    select(NodeHistory.node_id).where(
                        NodeHistory.itinerary_id == itin.id, NodeHistory.op == "update"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {day1.id, day4.id} <= set(ops)
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_settling_exact_dates_shift_refused_while_booked(
    db_session: AsyncSession,
) -> None:
    """A date-settle that would shift cards refuses while booked cards exist."""
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="settle-booked",
        timing_kind=ItineraryTimingKind.flexible,
    )
    try:
        anchor = datetime.now(UTC).date()
        node = await _scheduled_node(
            db_session, itin.id, starts_at=f"{anchor.isoformat()}T09:00:00+03:00"
        )
        node.status = NodeStatus.booked
        await db_session.commit()

        refused = await update_itinerary_details(
            db_session,
            _actor(),
            itin,
            fields={
                "timing_kind": ItineraryTimingKind.exact,
                "date_start": anchor + timedelta(days=5),
                "date_end": anchor + timedelta(days=12),
            },
        )
        assert isinstance(refused, ItineraryError)
        assert refused.detail == "booked_dates_locked"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_loosen_refused_while_booked_cards_exist(db_session: AsyncSession) -> None:
    itin = await _windowed_itinerary(db_session, title="loosen-booked")
    try:
        node = await _scheduled_node(db_session, itin.id, starts_at="2027-06-02T09:00:00+02:00")
        pinned = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 3, 18))
        assert isinstance(pinned, RetimeResult)
        node.status = NodeStatus.confirmed
        await db_session.commit()

        refused = await update_itinerary_details(
            db_session,
            _actor(),
            itin,
            fields={"timing_kind": ItineraryTimingKind.flexible},
        )
        assert isinstance(refused, ItineraryError)
        assert refused.detail == "booked_dates_locked"
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_retime_validates_range_and_derives_end_from_last_card(
    db_session: AsyncSession,
) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="retime-derive-end",
        timing_kind=ItineraryTimingKind.flexible,
    )
    try:
        bad = await retime_itinerary(
            db_session, _actor(), itin, date_start=date(2027, 3, 18), date_end=date(2027, 3, 17)
        )
        assert isinstance(bad, ItineraryError)
        assert bad.detail == "date_end_before_start"

        # No duration_nights, no prior span → the last scheduled card's date.
        await _scheduled_node(db_session, itin.id, starts_at="2027-06-01T10:00:00+02:00")
        await _scheduled_node(db_session, itin.id, starts_at="2027-06-04T10:00:00+02:00")
        await db_session.refresh(itin)
        anchor = itin.days_anchor
        assert anchor is not None
        result = await retime_itinerary(db_session, _actor(), itin, date_start=date(2027, 3, 18))
        assert isinstance(result, RetimeResult)
        await db_session.refresh(itin)
        # The Jun 4 card sat (Jun 4 − anchor) days in; it lands that far past Mar 18.
        expected_last = date(2027, 3, 18) + (date(2027, 6, 4) - anchor)
        assert itin.date_end == expected_last
    finally:
        await _cleanup(itin.id)
