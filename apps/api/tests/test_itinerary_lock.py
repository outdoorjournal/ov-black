"""Unit + integration coverage for S08 T02 lock / release primitives.

The service functions under test mutate real ``itineraries`` rows so we gate
this file on a live local Supabase Postgres (same pattern as
``test_itineraries.py``). Without the DB there is nothing meaningful to
assert — the SQL ``RETURNING`` semantics and the ``_check_write_gates`` gate
both need the real engine.

The old itinerary-level propose/approve/reopen state machine is gone (0044);
its replacement — per-node approve-all + the derived display status — is
covered in ``test_approve_all.py`` and ``test_display_status.py``. The
non-advisor lock tests run against a FORK: on a trunk the trunk guard
(``fork_required``) fires before the editor lock, so the fork is where the
lock outcome is observable for a USER actor.
"""

from __future__ import annotations

import socket
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import Itinerary, Node, NodeType
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    _check_write_gates,
    acquire_lock,
    add_node,
    create_itinerary,
    release_lock,
    update_node,
)
from sqlalchemy import text
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
async def db_session() -> AsyncSession:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(itinerary_ids: list[uuid.UUID], user_ids: list[uuid.UUID] | None = None) -> None:
    """Tear down fixture rows on a fresh engine so prior errors don't leak."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for itinerary_id in itinerary_ids:
                await conn.execute(
                    text("delete from public.edge_history where itinerary_id = :i"),
                    {"i": itinerary_id},
                )
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"),
                    {"i": itinerary_id},
                )
                await conn.execute(
                    text("delete from public.itineraries where id = :i"),
                    {"i": itinerary_id},
                )
            for uid in user_ids or []:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": uid})
    finally:
        await engine.dispose()


async def _seed_user(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal ``auth.users`` row so the locked_by FK can reference
    it. Supabase's ``auth.users`` has many columns but only ``id``,
    ``is_sso_user``, and ``is_anonymous`` are NOT NULL; the rest default or
    accept NULL. Using a random email keeps tests isolated.
    """
    await session.execute(
        text(
            "insert into auth.users (id, email, is_sso_user, is_anonymous) "
            "values (:id, :email, false, false)"
        ),
        {"id": user_id, "email": f"t02-{user_id}@test.local"},
    )
    await session.commit()
    return user_id


async def _seed_fork(session: AsyncSession, *, title: str) -> tuple[uuid.UUID, uuid.UUID]:
    """(trunk_id, fork_id) — the non-advisor lock tests need a fork, since a
    trunk refuses USER content writes (``fork_required``) before the editor
    lock is even consulted."""
    trunk = await create_itinerary(session, _system(), title=f"{title}-trunk")
    fork = await create_itinerary(session, _system(), title=f"{title}-fork")
    await session.execute(
        text(
            "update public.itineraries set forked_from_id = :t, fork_status = 'open' where id = :f"
        ),
        {"t": trunk.id, "f": fork.id},
    )
    await session.commit()
    return trunk.id, fork.id


def _advisor(user_id: uuid.UUID) -> ActorContext:
    return ActorContext(user_id=user_id, kind=ActorKind.ADVISOR, actor_id=None)


def _user(user_id: uuid.UUID) -> ActorContext:
    return ActorContext(user_id=user_id, kind=ActorKind.USER, actor_id=None)


def _system() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="t02-test")


# ── (a) acquire_lock on an unlocked itinerary ──────────────────────────────


@integration
@pytest.mark.asyncio
async def test_acquire_lock_on_unlocked_itinerary_flips_locked_by(
    db_session: AsyncSession,
) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    itinerary = await create_itinerary(db_session, _system(), title="lock-a")
    try:
        result = await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        assert isinstance(result, Itinerary)
        assert result.locked_by == advisor_id
        assert result.locked_at is not None
    finally:
        await _cleanup([itinerary.id], [advisor_id])


# ── (b) second acquire by different user returns LOCKED ────────────────────


@integration
@pytest.mark.asyncio
async def test_acquire_lock_by_different_user_returns_locked(
    db_session: AsyncSession,
) -> None:
    first = await _seed_user(db_session, uuid.uuid4())
    second = await _seed_user(db_session, uuid.uuid4())
    itinerary = await create_itinerary(db_session, _system(), title="lock-b")
    itinerary_id = itinerary.id  # stash before commits inside acquire_lock expire state
    try:
        first_res = await acquire_lock(db_session, _advisor(first), itinerary_id=itinerary_id)
        assert isinstance(first_res, Itinerary)

        second_res = await acquire_lock(db_session, _advisor(second), itinerary_id=itinerary_id)
        assert isinstance(second_res, ItineraryError)
        assert second_res.outcome is ItineraryOutcome.LOCKED
        assert second_res.detail == "already_locked"
    finally:
        await _cleanup([itinerary_id], [first, second])


# ── (c) same-user re-acquire is idempotent ─────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_same_user_reacquire_is_idempotent(
    db_session: AsyncSession,
) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    itinerary = await create_itinerary(db_session, _system(), title="lock-c")
    try:
        first = await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        assert isinstance(first, Itinerary)
        second = await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        assert isinstance(second, Itinerary)
        assert second.locked_by == advisor_id
    finally:
        await _cleanup([itinerary.id], [advisor_id])


# ── (d) release_lock is idempotent ─────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_release_lock_is_idempotent(db_session: AsyncSession) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    itinerary = await create_itinerary(db_session, _system(), title="lock-d")
    try:
        await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        first = await release_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        assert isinstance(first, Itinerary)
        assert first.locked_by is None
        assert first.locked_at is None

        second = await release_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        assert isinstance(second, Itinerary)
        assert second.locked_by is None
    finally:
        await _cleanup([itinerary.id], [advisor_id])


# ── (f) add_node by a non-advisor while locked returns LOCKED ──────────────


@integration
@pytest.mark.asyncio
async def test_add_node_by_non_advisor_while_locked_returns_locked(
    db_session: AsyncSession,
) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    other_user_id = uuid.uuid4()  # does not need to be in auth.users (no FK use)
    trunk_id, fork_id = await _seed_fork(db_session, title="lock-f")
    try:
        await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=fork_id)
        err = await add_node(
            db_session,
            _user(other_user_id),
            itinerary_id=fork_id,
            type=NodeType.experience,
            title="blocked",
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.LOCKED
        assert err.detail == "locked_by_advisor"
    finally:
        await _cleanup([fork_id, trunk_id], [advisor_id])


# ── (g) add_node by an advisor while locked succeeds ───────────────────────


@integration
@pytest.mark.asyncio
async def test_add_node_by_advisor_while_locked_succeeds(
    db_session: AsyncSession,
) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    itinerary = await create_itinerary(db_session, _system(), title="lock-g")
    try:
        await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=itinerary.id)
        node = await add_node(
            db_session,
            _advisor(advisor_id),
            itinerary_id=itinerary.id,
            type=NodeType.hotel,
            title="swap-hotel",
        )
        assert isinstance(node, Node)
        assert node.title == "swap-hotel"
    finally:
        await _cleanup([itinerary.id], [advisor_id])


# ── (h) update_node by non-advisor while locked returns LOCKED ─────────────


@integration
@pytest.mark.asyncio
async def test_update_node_by_non_advisor_while_locked_returns_locked(
    db_session: AsyncSession,
) -> None:
    advisor_id = await _seed_user(db_session, uuid.uuid4())
    user_id = uuid.uuid4()  # no FK use; just the acting user_id
    trunk_id, fork_id = await _seed_fork(db_session, title="lock-h")
    try:
        # Seed a node before the lock is taken so a USER can find it.
        node = await add_node(
            db_session,
            _user(user_id),
            itinerary_id=fork_id,
            type=NodeType.experience,
            title="orig",
        )
        assert isinstance(node, Node)

        # Advisor takes the lock.
        await acquire_lock(db_session, _advisor(advisor_id), itinerary_id=fork_id)

        err = await update_node(
            db_session,
            _user(user_id),
            itinerary_id=fork_id,
            node_id=node.id,
            title="blocked-edit",
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.LOCKED
        assert err.detail == "locked_by_advisor"
    finally:
        await _cleanup([fork_id, trunk_id], [advisor_id])


# ── Pure-unit guards on _check_write_gates (no DB fixture needed) ───────────


@integration
@pytest.mark.asyncio
async def test_check_write_gates_allows_advisor_even_without_user_id(
    db_session: AsyncSession,
) -> None:
    itinerary = await create_itinerary(db_session, _system(), title="lock-chk")
    try:
        # Simulate an advisor with no resolved user_id (edge case — advisors
        # still bypass the gate; the advisor router guard is the real check).
        advisor = ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="x")
        result = await _check_write_gates(db_session, itinerary.id, advisor)
        assert result is None
    finally:
        await _cleanup([itinerary.id])
