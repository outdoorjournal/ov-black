"""Soft-delete (0040): ``delete_node`` stamps ``deleted_at`` instead of purging
the row, and every graph read filters ``deleted_at is null`` so the node — plus
its dependent subtree (subgraph descendants + attached notes) and any touching
edge — vanishes from view while the row + its ``node_history`` lineage survive.

Two rules under test:
  * A **note** is feedback, not a commitment, so a user may remove ANY of their
    notes whatever the status (the firmed status gate does not apply).
  * A **regular / collection** node is deletable only while pre-firmed; an
    approved/booked/confirmed one still returns ``STATUS_LOCKED`` (demote first).

Runs against local Supabase so the recursive-CTE cascade and the read filters
are exercised for real (auto-skips when it isn't running).
"""

from __future__ import annotations

import socket
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import EdgeType, NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    add_edge,
    add_node,
    create_itinerary,
    delete_node,
    get_itinerary_graph,
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
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="test-soft-delete")


async def _deleted_at(session: AsyncSession, node_id: uuid.UUID) -> object | None:
    """Read the raw ``deleted_at`` straight from the row (bypasses the ORM cache)."""
    return (
        await session.execute(
            text("select deleted_at from public.nodes where id = :i"),
            {"i": node_id},
        )
    ).scalar_one_or_none()


async def _row_exists(session: AsyncSession, node_id: uuid.UUID) -> bool:
    return (
        await session.execute(
            text("select 1 from public.nodes where id = :i"),
            {"i": node_id},
        )
    ).scalar_one_or_none() is not None


async def _delete_history_count(session: AsyncSession, node_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                text(
                    "select count(*) from public.node_history where node_id = :i and op = 'delete'"
                ),
                {"i": node_id},
            )
        ).scalar_one()
    )


@integration
@pytest.mark.asyncio
async def test_delete_note_hides_from_graph_but_keeps_row(
    db_session: AsyncSession,
) -> None:
    """Deleting a note stamps ``deleted_at`` + writes a delete-history row; the
    node disappears from the graph read but the row itself is preserved."""
    itinerary = await create_itinerary(db_session, _actor(), title="soft-del note")
    try:
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="dinner between these?",
            starts_at="2025-07-02T19:30:00+09:00",
        )
        assert not isinstance(note, ItineraryError)

        err = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=note.id)
        assert err is None

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        assert view.nodes == []  # gone from view

        assert await _row_exists(db_session, note.id)  # row preserved
        assert await _deleted_at(db_session, note.id) is not None  # tombstoned
        assert await _delete_history_count(db_session, note.id) == 1  # lineage kept
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_note_bypasses_firmed_status_gate(
    db_session: AsyncSession,
) -> None:
    """A note is feedback, not a commitment — even an *approved* one deletes."""
    itinerary = await create_itinerary(db_session, _actor(), title="soft-del firmed note")
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            status=NodeStatus.pending,
            title="tea ceremony",
        )
        assert not isinstance(host, ItineraryError)
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.approved,  # firmed — would block a regular node
            title="confirmed with the house",
            attached_to_node_id=host.id,
        )
        assert not isinstance(note, ItineraryError)

        err = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=note.id)
        assert err is None
        assert await _deleted_at(db_session, note.id) is not None

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        assert {n.id for n in view.nodes} == {host.id}  # host stays, note gone
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_prefirmed_regular_node_soft_deletes(
    db_session: AsyncSession,
) -> None:
    """A regular (collection) card that isn't approved/booked deletes softly."""
    itinerary = await create_itinerary(db_session, _actor(), title="soft-del card")
    try:
        # No starts_at, no attachment → a timeless Collection / wish-list item.
        card = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            status=NodeStatus.pending,
            title="maybe this ryokan",
        )
        assert not isinstance(card, ItineraryError)

        err = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=card.id)
        assert err is None
        assert await _deleted_at(db_session, card.id) is not None

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        assert view.nodes == []
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_firmed_regular_node_is_blocked(
    db_session: AsyncSession,
) -> None:
    """An approved regular node still refuses deletion (demote-before-delete)."""
    itinerary = await create_itinerary(db_session, _actor(), title="firmed card")
    try:
        card = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            status=NodeStatus.approved,
            title="booked ryokan",
        )
        assert not isinstance(card, ItineraryError)

        err = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=card.id)
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.STATUS_LOCKED
        assert err.detail == "demote_before_delete"
        assert await _deleted_at(db_session, card.id) is None  # untouched

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        assert {n.id for n in view.nodes} == {card.id}  # still visible
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_cascades_to_attached_notes_and_edges(
    db_session: AsyncSession,
) -> None:
    """Deleting a host cascades to its attached notes and drops touching edges —
    the same set the old ON DELETE CASCADE removed — so nothing dangles."""
    itinerary = await create_itinerary(db_session, _actor(), title="cascade")
    try:
        host = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            status=NodeStatus.pending,
            title="host card",
        )
        neighbour = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            status=NodeStatus.pending,
            title="next card",
        )
        assert not isinstance(host, ItineraryError)
        assert not isinstance(neighbour, ItineraryError)
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="ride-along note",
            attached_to_node_id=host.id,
        )
        assert not isinstance(note, ItineraryError)
        edge = await add_edge(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            from_node_id=host.id,
            to_node_id=neighbour.id,
            type=EdgeType.follows,
        )
        assert not isinstance(edge, ItineraryError)

        err = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=host.id)
        assert err is None

        # Host AND its attached note are both tombstoned.
        assert await _deleted_at(db_session, host.id) is not None
        assert await _deleted_at(db_session, note.id) is not None
        # The unrelated neighbour is untouched.
        assert await _deleted_at(db_session, neighbour.id) is None

        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        assert {n.id for n in view.nodes} == {neighbour.id}
        assert view.edges == []  # the follows-edge touched a hidden node → dropped
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_is_idempotent(db_session: AsyncSession) -> None:
    """A second delete is a no-op: still one delete-history row, still hidden."""
    itinerary = await create_itinerary(db_session, _actor(), title="idempotent")
    try:
        note = await add_node(
            db_session,
            _actor(),
            itinerary_id=itinerary.id,
            type=NodeType.note,
            status=NodeStatus.pending,
            title="delete me twice",
            starts_at="2025-07-02T19:30:00+09:00",
        )
        assert not isinstance(note, ItineraryError)

        first = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=note.id)
        stamp = await _deleted_at(db_session, note.id)
        second = await delete_node(db_session, _actor(), itinerary_id=itinerary.id, node_id=note.id)
        assert first is None and second is None
        # Tombstone unchanged and no duplicate history row from the no-op.
        assert await _deleted_at(db_session, note.id) == stamp
        assert await _delete_history_count(db_session, note.id) == 1
    finally:
        await _cleanup(itinerary.id)
