"""Race coverage for S08 T03: agent writes queue while advisor holds the lock.

Exercises the in-memory queue + drain semantics end-to-end against a real
Postgres: advisor acquires the lock, then ``asyncio.gather`` interleaves an
agent card persist (which must enqueue) with an advisor node update (which
must succeed). After ``release_lock`` runs ``drain_queue``, the enqueued
mutation replays and ``node_history`` carries both rows with correct actor
attribution. Gated on a running local Supabase (port 54322) — skipped on a
fresh checkout with no Docker.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import Itinerary, Node, NodeHistory, NodeType
from app.services.agent import (
    _agent_write_queue,
    _persist_proposed_card,
    drain_queue,
    queue_depth,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    acquire_lock,
    add_node,
    create_itinerary,
    release_lock,
    update_node,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    pass


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
async def engine_factory():
    """Yield an engine + sessionmaker pair and dispose on teardown.

    The race test opens its own sessions (one per gathered coroutine) so
    a single shared ``AsyncSession`` fixture wouldn't suffice — asyncpg
    connections are not safe to multiplex across coroutines.
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield engine, maker
    finally:
        await engine.dispose()


async def _seed_user(maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> uuid.UUID:
    async with maker() as s:
        await s.execute(
            text(
                "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                "values (:id, :email, false, false)"
            ),
            {"id": user_id, "email": f"t03-{user_id}@test.local"},
        )
        await s.commit()
    return user_id


async def _cleanup(itinerary_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.edge_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.node_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.nodes where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
            for uid in user_ids:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": uid})
    finally:
        await engine.dispose()


def _advisor(user_id: uuid.UUID) -> ActorContext:
    return ActorContext(user_id=user_id, kind=ActorKind.ADVISOR, actor_id=None)


def _agent(session_id: uuid.UUID) -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.AGENT, actor_id=str(session_id))


def _system() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="t03-test")


# ── Scenario 1: agent write queues under lock; release drains it ───────────


@integration
@pytest.mark.asyncio
async def test_agent_write_queues_under_lock_and_drains_on_release(engine_factory, caplog) -> None:
    engine, maker = engine_factory

    advisor_id = await _seed_user(maker, uuid.uuid4())
    session_id = uuid.uuid4()

    async with maker() as setup:
        itinerary = await create_itinerary(setup, _system(), title="race-1")
    itinerary_id = itinerary.id

    # Isolate the queue: other tests in the session must not leak entries
    # into or out of this scenario's assertions.
    _agent_write_queue.pop(itinerary_id, None)

    try:
        # Seed one node the advisor can update concurrently.
        async with maker() as setup:
            seed_node = await add_node(
                setup,
                _system(),
                itinerary_id=itinerary_id,
                type=NodeType.hotel,
                title="orig-hotel",
            )
        assert isinstance(seed_node, Node)

        # Advisor takes the lock.
        async with maker() as lock_sess:
            lock_result = await acquire_lock(
                lock_sess, _advisor(advisor_id), itinerary_id=itinerary_id
            )
        assert isinstance(lock_result, Itinerary)
        assert lock_result.locked_by == advisor_id

        # Now race: agent persists a card (must enqueue) while the advisor
        # updates the seeded hotel node (must succeed).
        async def _agent_call() -> uuid.UUID | None:
            async with maker() as agent_sess:
                return await _persist_proposed_card(
                    agent_sess,
                    session_id=session_id,
                    itinerary_id=itinerary_id,
                    agentcore_session_id=str(session_id),
                    source="ov",
                    source_id="villa-42",
                    snapshot={"title": "ov-villa", "price": 4200},
                )

        async def _advisor_update():
            async with maker() as advisor_sess:
                return await update_node(
                    advisor_sess,
                    _advisor(advisor_id),
                    itinerary_id=itinerary_id,
                    node_id=seed_node.id,
                    title="swapped hotel",
                )

        with caplog.at_level("INFO", logger="ov_black.agent.service"):
            agent_out, advisor_out = await asyncio.gather(_agent_call(), _advisor_update())

        # Agent persist returned None (queued, not written).
        assert agent_out is None
        # Advisor update succeeded and flipped the title.
        assert isinstance(advisor_out, Node)
        assert advisor_out.title == "swapped hotel"
        # Queue now holds the agent mutation.
        assert queue_depth(itinerary_id) == 1
        queued = _agent_write_queue[itinerary_id][0]
        assert queued.op == "add_node"
        assert queued.session_id == session_id
        # Log line fired with the expected event name.
        assert any(
            record.getMessage() == "itinerary.agent_write_queued" for record in caplog.records
        )
        caplog.clear()

        # Advisor releases the lock and drains the queue.
        async with maker() as rel_sess:
            released = await release_lock(rel_sess, _advisor(advisor_id), itinerary_id=itinerary_id)
        assert isinstance(released, Itinerary)
        assert released.locked_by is None

        with caplog.at_level("INFO", logger="ov_black.agent.service"):
            replayed_count = await drain_queue(maker, itinerary_id)
        assert replayed_count == 1
        assert queue_depth(itinerary_id) == 0
        assert any(
            record.getMessage() == "itinerary.agent_write_replayed" for record in caplog.records
        )

        # The replayed node exists and carries AGENT provenance.
        async with maker() as verify:
            node_rows = (
                (await verify.execute(select(Node).where(Node.itinerary_id == itinerary_id)))
                .scalars()
                .all()
            )
            titles = {n.title for n in node_rows}
            assert "ov-villa" in titles  # replayed agent node
            assert "swapped hotel" in titles  # advisor update

            history_rows = (
                (
                    await verify.execute(
                        select(NodeHistory)
                        .where(NodeHistory.itinerary_id == itinerary_id)
                        .order_by(NodeHistory.occurred_at)
                    )
                )
                .scalars()
                .all()
            )
            actor_kinds = [row.actor_kind for row in history_rows]
            assert "advisor" in actor_kinds  # advisor's update row
            assert "agent" in actor_kinds  # replayed agent insert row
    finally:
        _agent_write_queue.pop(itinerary_id, None)
        await _cleanup(itinerary_id, [advisor_id])


# ── Scenario 2: queue_depth is 0 for an unknown itinerary_id ───────────────


def test_queue_depth_zero_for_unknown_itinerary() -> None:
    assert queue_depth(uuid.uuid4()) == 0


# ── Scenario 3: drain on empty queue is a no-op returning 0 ────────────────


@pytest.mark.asyncio
async def test_drain_queue_on_empty_returns_zero(engine_factory) -> None:
    _engine, maker = engine_factory
    assert await drain_queue(maker, uuid.uuid4()) == 0
