"""Note anchoring (0014 dual-mode) + the move-keeps-starts_at-in-sync invariant.

A ``note`` node must satisfy ``notes_anchored_or_attached``: exactly one of
``attached_to_node_id`` (an annotation riding a host) or ``starts_at`` (a
free-standing item). These exercise ``add_node`` / ``update_node`` /
``get_itinerary_graph`` end-to-end against local Supabase so the real CHECK,
the ``Range`` construction, and the read serialization are all in the loop.
"""

from __future__ import annotations

import socket
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    SchedulePlacement,
    add_node,
    create_itinerary,
    get_itinerary_graph,
    update_node,
)
from sqlalchemy import text
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
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="test-notes")


@integration
@pytest.mark.asyncio
async def test_free_standing_note_persists_starts_at_and_mirrors_metadata(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="notes free")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="something for dinner between these",
            starts_at="2025-07-02T19:30:00+09:00",
            duration_minutes=90,
        )
        assert not isinstance(node, ItineraryError)
        assert node.attached_to_node_id is None
        # metadata mirrored so the web timeline (reads metadata.start_time) renders it.
        assert node.metadata_["start_time"] == "2025-07-02T19:30:00+09:00"
        assert node.metadata_["tz_offset_minutes"] == 540

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        (read,) = view.nodes
        assert read.type is NodeType.note
        assert read.starts_at == "2025-07-02T19:30:00+09:00"
        assert read.duration_minutes == 90
        assert read.attached_to_node_id is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_attached_note_persists_attachment_and_no_range(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="notes attached")
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            status=NodeStatus.pending,
            title="Tea ceremony at 1:30",
        )
        assert not isinstance(host, ItineraryError)
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="why are we doing this at 1:30?",
            attached_to_node_id=host.id,
        )
        assert not isinstance(note, ItineraryError)
        assert note.attached_to_node_id == host.id
        assert note.starts_at is None

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        read_note = next(n for n in view.nodes if n.id == note.id)
        assert read_note.attached_to_node_id == host.id
        assert read_note.starts_at is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_note_metadata_start_time_is_inert_content(
    db_session: AsyncSession,
) -> None:
    # Phase 6 (doc/itin-time.md): metadata.start_time is retired as an input.
    # A note posted with only a metadata start (no typed ``starts_at``) is a
    # timeless Collection note — the mirror is read-compat output, never read
    # back as a schedule.
    itinerary = await create_itinerary(db_session, _actor(), title="notes meta")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="New note",
            metadata={"start_time": "2025-07-02T12:00:00+09:00"},
        )
        assert not isinstance(node, ItineraryError)
        assert node.starts_at is None
        assert node.schedule_kind is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_note_without_any_anchor_is_collection_note(
    db_session: AsyncSession,
) -> None:
    # A timeless, unattached note is a valid Collection note (0035): it lives in
    # the wish list unscheduled rather than being rejected.
    itinerary = await create_itinerary(db_session, _actor(), title="notes none")
    try:
        result = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="floating",
        )
        assert not isinstance(result, ItineraryError)
        assert result.starts_at is None
        assert result.attached_to_node_id is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_note_with_both_anchors_is_validation_error(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="notes both")
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="Host",
        )
        assert not isinstance(host, ItineraryError)
        result = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="both",
            attached_to_node_id=host.id,
            starts_at="2025-07-02T19:30:00+09:00",
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_attached_note_cross_itinerary_is_invalid_parent(
    db_session: AsyncSession,
) -> None:
    other = await create_itinerary(db_session, _actor(), title="notes other")
    itinerary = await create_itinerary(db_session, _actor(), title="notes host")
    try:
        foreign = await add_node(
            db_session,
            _actor(),
            itinerary_id=other.id,
            type=NodeType.experience,
            title="Elsewhere",
        )
        assert not isinstance(foreign, ItineraryError)
        result = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="cross",
            attached_to_node_id=foreign.id,
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.INVALID_PARENT
    finally:
        await _cleanup(itinerary.id)
        await _cleanup(other.id)


@integration
@pytest.mark.asyncio
async def test_attached_to_node_id_rejected_on_non_note(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="notes nonnote")
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="Host",
        )
        assert not isinstance(host, ItineraryError)
        result = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="not a note",
            attached_to_node_id=host.id,
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_move_free_standing_note_via_placement(
    db_session: AsyncSession,
) -> None:
    # A move is a trip-terms placement (web `moveNode` / agent `move_node`,
    # Phase 6): the kernel builds the schedule and starts_at is derived
    # output. The note keeps its own zone (+09:00 here).
    itinerary = await create_itinerary(db_session, _actor(), title="notes move")
    try:
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="dinner?",
            starts_at="2025-07-02T19:30:00+09:00",
        )
        assert not isinstance(note, ItineraryError)
        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=note.id,
            placement=SchedulePlacement(day_index=1, minute_of_day=21 * 60),
        )
        assert not isinstance(moved, ItineraryError)
        assert moved.schedule_kind == "relative"
        assert moved.start_day_offset == 0
        assert str(moved.start_wall_time) == "21:00:00"
        assert moved.starts_at is not None
        assert moved.metadata_["start_time"].endswith("+09:00")  # promised wall clock
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_metadata_patch_schedules_then_unschedules_non_note(
    db_session: AsyncSession,
) -> None:
    # Collection ↔ timeline for a non-note (Phase 6): a metadata patch is
    # content-only — the ONLY way onto the timeline is a typed placement, and
    # the only way back to the Collection is ``clear_schedule``.
    itinerary = await create_itinerary(db_session, _actor(), title="collection sched")
    try:
        node = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="Tea ceremony",
        )
        assert not isinstance(node, ItineraryError)
        assert node.starts_at is None  # lands in the Collection, unscheduled

        # A metadata patch carrying start_time is inert content — no schedule.
        patched = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            metadata={"start_time": "2025-07-02T13:30:00+09:00"},
        )
        assert not isinstance(patched, ItineraryError)
        assert patched.starts_at is None

        # Placement schedules; the kernel owns the construction.
        scheduled = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            placement=SchedulePlacement(day_index=1, minute_of_day=13 * 60 + 30),
        )
        assert not isinstance(scheduled, ItineraryError)
        assert scheduled.starts_at is not None
        assert str(scheduled.start_wall_time) == "13:30:00"

        # A later content patch does NOT unschedule …
        content_only = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            metadata={"note": "maybe later"},
        )
        assert not isinstance(content_only, ItineraryError)
        assert content_only.starts_at is not None

        # … clear_schedule does.
        unscheduled = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=node.id,
            clear_schedule=True,
        )
        assert not isinstance(unscheduled, ItineraryError)
        assert unscheduled.starts_at is None
        assert unscheduled.schedule_kind is None
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_unschedule_note_returns_to_collection(
    db_session: AsyncSession,
) -> None:
    # A free-standing (timed) note dragged back to the Collection becomes a
    # timeless, unattached note — legal under the relaxed 0035 CHECK.
    itinerary = await create_itinerary(db_session, _actor(), title="note uncollect")
    try:
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            title="dinner?",
            starts_at="2025-07-02T19:30:00+09:00",
        )
        assert not isinstance(note, ItineraryError)
        unscheduled = await update_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            node_id=note.id,
            clear_schedule=True,
        )
        assert not isinstance(unscheduled, ItineraryError)
        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        (read,) = view.nodes
        assert read.starts_at is None
        assert read.attached_to_node_id is None
    finally:
        await _cleanup(itinerary.id)
