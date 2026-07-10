"""Status-aware mutation gates (M004/G1 — TravelGraph_Analysis §11).

Two layers:

1. Pure unit tests over the full ``status × actor`` matrix for
   ``_check_status_gate`` and ``compute_lock_reason`` — no DB.
2. Integration tests against a local Supabase Postgres proving the gate fires
   inside the real ``update_node`` / ``delete_node`` service path, that an
   advisor demotion works and is logged, and that ``lock_reason`` rides on the
   graph-read row. Gated on ``_supabase_running()`` so a fresh checkout skips.
"""

from __future__ import annotations

import socket
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import Node, NodeHistory, NodeStatus, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    _check_status_gate,
    add_node,
    compute_lock_reason,
    create_itinerary,
    delete_node,
    get_itinerary_graph,
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
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322

_FIRMED = (NodeStatus.approved, NodeStatus.booked, NodeStatus.confirmed)
_FREE = (NodeStatus.pending, NodeStatus.discarded)
_NON_ADVISOR = (ActorKind.USER, ActorKind.AGENT, ActorKind.SYSTEM)


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


def _actor(kind: ActorKind) -> ActorContext:
    # A real user id only matters for the lock gate, not the status gate.
    return ActorContext(user_id=None, kind=kind, actor_id=f"gate-{kind.value}")


# ── Pure unit: compute_lock_reason ─────────────────────────────────────────


@pytest.mark.parametrize("status", _FIRMED)
def test_lock_reason_set_for_firmed(status: NodeStatus) -> None:
    assert compute_lock_reason(status) == "status_locked"


@pytest.mark.parametrize("status", _FREE)
def test_lock_reason_none_for_pre_firmed(status: NodeStatus) -> None:
    assert compute_lock_reason(status) is None


# ── Pure unit: _check_status_gate matrix (status × actor × field-edit) ──────


@pytest.mark.parametrize("status", _FREE)
@pytest.mark.parametrize(
    "kind", [ActorKind.USER, ActorKind.AGENT, ActorKind.ADVISOR, ActorKind.SYSTEM]
)
@pytest.mark.parametrize("mutates_other", [True, False])
def test_gate_allows_any_actor_on_pre_firmed(
    status: NodeStatus, kind: ActorKind, mutates_other: bool
) -> None:
    """pending / discarded are freely editable by everyone."""
    assert (
        _check_status_gate(
            current_status=status, actor=_actor(kind), mutates_other_fields=mutates_other
        )
        is None
    )


@pytest.mark.parametrize("status", _FIRMED)
@pytest.mark.parametrize("kind", list(_NON_ADVISOR))
@pytest.mark.parametrize("mutates_other", [True, False])
def test_gate_blocks_non_advisor_on_firmed(
    status: NodeStatus, kind: ActorKind, mutates_other: bool
) -> None:
    """A firmed node is fully immutable to traveler / agent / system."""
    err = _check_status_gate(
        current_status=status, actor=_actor(kind), mutates_other_fields=mutates_other
    )
    assert err is not None
    assert err.outcome is ItineraryOutcome.STATUS_LOCKED
    assert err.detail == "status_locked"


@pytest.mark.parametrize("status", _FIRMED)
def test_gate_allows_advisor_pure_status_change_on_firmed(status: NodeStatus) -> None:
    """The advisor escape hatch: a pure status change (demote / cancel / advance)."""
    assert (
        _check_status_gate(
            current_status=status, actor=_actor(ActorKind.ADVISOR), mutates_other_fields=False
        )
        is None
    )


@pytest.mark.parametrize("status", _FIRMED)
def test_gate_blocks_advisor_field_edit_on_firmed(status: NodeStatus) -> None:
    """An advisor must demote a firmed node before editing any other field."""
    err = _check_status_gate(
        current_status=status, actor=_actor(ActorKind.ADVISOR), mutates_other_fields=True
    )
    assert err is not None
    assert err.outcome is ItineraryOutcome.STATUS_LOCKED
    assert err.detail == "demote_before_edit"


# ── Integration: the gate inside the real service path ─────────────────────


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
            for itinerary_id in itinerary_ids:
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


async def _seed_fork(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """(trunk_id, fork_id). Content mutations by USER/AGENT are reserved to
    forks by the trunk guard, so the G1 status-gate tests run inside a fork —
    the traveler's working copy — where only the status gate applies."""
    trunk = await create_itinerary(session, _actor(ActorKind.ADVISOR), title="gate baseline")
    fork = await create_itinerary(session, _actor(ActorKind.ADVISOR), title="gate fork")
    await session.execute(
        text(
            "update public.itineraries set forked_from_id = :t, fork_status = 'open' where id = :f"
        ),
        {"t": trunk.id, "f": fork.id},
    )
    await session.commit()
    return trunk.id, fork.id


async def _booked_node(session: AsyncSession, itinerary_id: uuid.UUID) -> Node:
    """Seed a booked node. Creation isn't gated — only later edits are."""
    node = await add_node(
        session,
        _actor(ActorKind.SYSTEM),
        itinerary_id=itinerary_id,
        type=NodeType.hotel,
        status=NodeStatus.booked,
        title="Aman Tokyo",
    )
    assert isinstance(node, Node)
    return node


@integration
@pytest.mark.asyncio
async def test_traveler_edit_of_booked_node_refused(db_session: AsyncSession) -> None:
    trunk_id, fork_id = await _seed_fork(db_session)
    try:
        node = await _booked_node(db_session, fork_id)
        err = await update_node(
            db_session,
            _actor(ActorKind.USER),
            itinerary_id=fork_id,
            node_id=node.id,
            title="hands off",
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.STATUS_LOCKED
        assert err.detail == "status_locked"
        # The refusal didn't mutate the row.
        fresh = (
            await db_session.execute(select(Node.title).where(Node.id == node.id))
        ).scalar_one()
        assert fresh == "Aman Tokyo"
    finally:
        await _cleanup(fork_id, trunk_id)


@integration
@pytest.mark.asyncio
async def test_agent_status_flip_of_confirmed_node_refused(db_session: AsyncSession) -> None:
    """The agent (non-advisor at the service layer) can't even discard a firmed node."""
    itinerary = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="gate")
    try:
        node = await add_node(
            db_session,
            _actor(ActorKind.SYSTEM),
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            status=NodeStatus.confirmed,
            title="Tea ceremony",
        )
        assert isinstance(node, Node)
        err = await update_node(
            db_session,
            _actor(ActorKind.AGENT),
            itinerary_id=itinerary.id,
            node_id=node.id,
            status=NodeStatus.discarded,
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.STATUS_LOCKED
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_direct_booked_promotion_via_update_node_refused(db_session: AsyncSession) -> None:
    """The money gate (M005/I3) can't be bypassed: a direct flip to booked is refused.

    Booking authority is ``services.bookings`` (a covering paid invoice line, a fresh
    offer, a recorded booking). ``update_node`` must refuse a straight
    pending→booked promotion with ``CONFLICT`` / ``use_booking_flow`` rather than
    silently moving the node — and the router maps that to 409, not 500.
    """
    itinerary = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="gate")
    try:
        node = await add_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            status=NodeStatus.approved,
            title="Aman Tokyo",
        )
        assert isinstance(node, Node)
        for target in (NodeStatus.booked, NodeStatus.confirmed):
            err = await update_node(
                db_session,
                _actor(ActorKind.ADVISOR),
                itinerary_id=itinerary.id,
                node_id=node.id,
                status=target,
            )
            assert isinstance(err, ItineraryError)
            assert err.outcome is ItineraryOutcome.CONFLICT
            assert err.detail == "use_booking_flow"
        # The refusals didn't move the node off approved.
        fresh = (
            await db_session.execute(select(Node.status).where(Node.id == node.id))
        ).scalar_one()
        assert fresh is NodeStatus.approved
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_advisor_demotion_works_and_is_logged(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="gate")
    try:
        node = await _booked_node(db_session, itinerary.id)
        demoted = await update_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=itinerary.id,
            node_id=node.id,
            status=NodeStatus.pending,
        )
        assert isinstance(demoted, Node)
        assert demoted.status is NodeStatus.pending

        rows = (
            (
                await db_session.execute(
                    select(NodeHistory)
                    .where(NodeHistory.node_id == node.id)
                    .order_by(NodeHistory.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        # insert (seed) + update (demotion) — the visible, attributed note.
        assert [r.op for r in rows] == ["insert", "update"]
        demotion = rows[-1]
        assert demotion.actor_kind == ActorKind.ADVISOR.value
        assert demotion.before["status"] == NodeStatus.booked.value
        assert demotion.after["status"] == NodeStatus.pending.value
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_advisor_field_edit_on_booked_node_refused(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="gate")
    try:
        node = await _booked_node(db_session, itinerary.id)
        err = await update_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=itinerary.id,
            node_id=node.id,
            title="renamed without demoting",
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.STATUS_LOCKED
        assert err.detail == "demote_before_edit"
    finally:
        await _cleanup(itinerary.id)


@integration
@pytest.mark.asyncio
async def test_demote_then_edit_flow(db_session: AsyncSession) -> None:
    """After an advisor demotes a firmed node, it's freely editable again."""
    trunk_id, fork_id = await _seed_fork(db_session)
    try:
        node = await _booked_node(db_session, fork_id)
        await update_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=fork_id,
            node_id=node.id,
            status=NodeStatus.pending,
        )
        edited = await update_node(
            db_session,
            _actor(ActorKind.USER),
            itinerary_id=fork_id,
            node_id=node.id,
            title="now editable",
        )
        assert isinstance(edited, Node)
        assert edited.title == "now editable"
    finally:
        await _cleanup(fork_id, trunk_id)


@integration
@pytest.mark.asyncio
async def test_delete_of_booked_node_refused_for_all(db_session: AsyncSession) -> None:
    trunk_id, fork_id = await _seed_fork(db_session)
    try:
        node = await _booked_node(db_session, fork_id)
        for kind in (ActorKind.USER, ActorKind.ADVISOR):
            err = await delete_node(
                db_session,
                _actor(kind),
                itinerary_id=fork_id,
                node_id=node.id,
            )
            assert isinstance(err, ItineraryError)
            assert err.outcome is ItineraryOutcome.STATUS_LOCKED
            assert err.detail == "demote_before_delete"
        # Still present.
        assert (
            await db_session.execute(select(Node.id).where(Node.id == node.id))
        ).scalar_one_or_none() == node.id
    finally:
        await _cleanup(fork_id, trunk_id)


@integration
@pytest.mark.asyncio
async def test_lock_reason_rides_on_graph_read(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(db_session, _actor(ActorKind.ADVISOR), title="gate")
    try:
        booked = await _booked_node(db_session, itinerary.id)
        pending = await add_node(
            db_session,
            _actor(ActorKind.SYSTEM),
            itinerary_id=itinerary.id,
            type=NodeType.meal,
            status=NodeStatus.pending,
            title="Sukiyabashi Jiro",
        )
        assert isinstance(pending, Node)
        view = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(view, ItineraryError)
        by_id = {n.id: n for n in view.nodes}
        assert by_id[booked.id].lock_reason == "status_locked"
        assert by_id[pending.id].lock_reason is None
    finally:
        await _cleanup(itinerary.id)
