"""Concurrent idempotent session opens collapse to ONE live session.

Regression for the intake double-open: React strict-mode double-effects fire
``POST /sessions`` twice within microseconds, both used to miss the reuse
SELECT, and the scope ended up with duplicate live sessions — each carrying
its own seeded-opener turn. ``open_or_reuse_session`` now serializes the scope
with a transaction-scoped Postgres advisory lock, so the losers block until
the winner commits and then reuse its row.

Integration-only (drives real concurrency through local Supabase Postgres);
gated on ``_supabase_running()`` like the other DB-backed suites.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import TYPE_CHECKING

import pytest
from app.services.agent import ActorContext, SessionOutcome, open_or_reuse_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322

OPENER = "Where shall we take you?"


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


async def _seed_owner_and_client(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    """One advisor auth user owning one client row (test_me.py conventions)."""
    owner = uuid.uuid4()
    client_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                insert into auth.users (id, email, aud, role, instance_id)
                values (:id, :email, 'authenticated', 'authenticated',
                        '00000000-0000-0000-0000-000000000000')
                """
            ),
            {"id": owner, "email": f"{owner}@race-test.local"},
        )
        await conn.execute(
            text(
                """
                insert into public.clients (id, owner_id, full_name, email)
                values (:id, :owner, 'Race Client', :email)
                """
            ),
            {"id": client_id, "owner": owner, "email": f"{client_id}@race-test.local"},
        )
    return owner, client_id


async def _cleanup(engine: AsyncEngine, owner: uuid.UUID, client_id: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "delete from public.agent_turns where session_id in "
                "(select id from public.agent_sessions where client_id = :c)"
            ),
            {"c": client_id},
        )
        await conn.execute(
            text("delete from public.agent_sessions where client_id = :c"), {"c": client_id}
        )
        await conn.execute(text("delete from public.clients where id = :c"), {"c": client_id})
        await conn.execute(text("delete from auth.users where id = :u"), {"u": owner})


@integration
@pytest.mark.asyncio
async def test_concurrent_opens_reuse_one_session() -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner, client_id = await _seed_owner_and_client(engine)
    actor = ActorContext(user_id=owner, actor_kind="advisor", actor_id=str(owner))

    async def open_once() -> uuid.UUID:
        outcome, row, _pinned = await open_or_reuse_session(
            maker,
            actor=actor,
            client_id=client_id,
            seeded_opener=OPENER,
        )
        assert outcome is SessionOutcome.OK
        assert row is not None
        return row.id

    try:
        ids = set(await asyncio.gather(*(open_once() for _ in range(5))))
        # Everyone landed on ONE session…
        assert len(ids) == 1

        async with maker() as s:
            live_count = (
                await s.execute(
                    text(
                        "select count(*) from public.agent_sessions "
                        "where client_id = :c and ended_at is null and archived_at is null"
                    ),
                    {"c": client_id},
                )
            ).scalar_one()
            # …and the seeded opener was written exactly once (turn 0), not
            # once per racer.
            opener_count = (
                await s.execute(
                    text(
                        "select count(*) from public.agent_turns where session_id in "
                        "(select id from public.agent_sessions where client_id = :c)"
                    ),
                    {"c": client_id},
                )
            ).scalar_one()
        assert live_count == 1
        assert opener_count == 1
    finally:
        await _cleanup(engine, owner, client_id)
        await engine.dispose()
