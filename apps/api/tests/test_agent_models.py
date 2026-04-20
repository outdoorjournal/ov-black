"""Integration tests for the AgentSession + AgentTurn SQLAlchemy models.

Guards against schema drift between
``supabase/migrations/0004_agent_sessions.sql`` and the hand-aligned models
in ``app/models/agent.py``. Mirrors ``tests/test_client_models.py``: insert
through the async engine, read back, and assert enums coerce and timestamps
arrive tz-aware. Also asserts the RLS-on-zero-policies posture and
unique(session_id, turn_index).

Requires ``supabase start`` (Postgres on port 54322). When the DB is
unreachable the module is skipped.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import AgentSession, AgentTurn, Client, TurnRole

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


pytestmark = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase Postgres (127.0.0.1:54322) not running — `supabase start` first",
)


@pytest_asyncio.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _insert_auth_user(session: AsyncSession, user_id: uuid.UUID, email: str) -> None:
    await session.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": user_id, "email": email},
    )


async def _make_client(session: AsyncSession, advisor_id: uuid.UUID) -> uuid.UUID:
    client = Client(
        owner_id=advisor_id,
        full_name="Agent Client",
        email=f"client-{uuid.uuid4().hex[:8]}@example.com",
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client.id


async def _cleanup(
    session: AsyncSession,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID | None,
) -> None:
    # agent_sessions and agent_turns cascade on clients delete.
    if client_id is not None:
        await session.execute(
            text("delete from public.clients where id = :id"), {"id": client_id}
        )
    await session.execute(
        text("delete from auth.users where id = :id"), {"id": advisor_id}
    )
    await session.commit()


@pytest.mark.asyncio
async def test_agent_session_round_trip(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)
        client_id = await _make_client(session, advisor_id)

        agent_session = AgentSession(
            client_id=client_id,
            agentcore_session_id="runtime-session-abc123",
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)

        fetched = (
            await session.execute(
                select(AgentSession).where(AgentSession.id == agent_session.id)
            )
        ).scalar_one()
        assert fetched.client_id == client_id
        assert fetched.agentcore_session_id == "runtime-session-abc123"
        assert fetched.ended_at is None
        assert isinstance(fetched.started_at, datetime)
        assert fetched.started_at.tzinfo is not None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_agent_turn_round_trip_with_defaults(session: AsyncSession) -> None:
    """A minimal AgentTurn populates server defaults on nullable columns."""
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)
        client_id = await _make_client(session, advisor_id)

        agent_session = AgentSession(
            client_id=client_id,
            agentcore_session_id="runtime-session-defaults",
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)

        turn = AgentTurn(
            session_id=agent_session.id,
            turn_index=0,
            role=TurnRole.user,
            actor_kind="human",
        )
        session.add(turn)
        await session.commit()

        fetched = (
            await session.execute(
                select(AgentTurn).where(AgentTurn.session_id == agent_session.id)
            )
        ).scalar_one()

        assert fetched.turn_index == 0
        assert fetched.role is TurnRole.user
        # Server defaults populate the empty-string content + zero retries.
        assert fetched.content == ""
        assert fetched.retried == 0
        # Nullable columns stay null when omitted.
        assert fetched.model is None
        assert fetched.latency_ms is None
        assert fetched.first_token_ms is None
        assert fetched.actor_id is None
        assert fetched.error_reason is None
        # Timestamps arrive tz-aware.
        assert isinstance(fetched.created_at, datetime)
        assert fetched.created_at.tzinfo is not None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_turn_role_enum_accepts_all_five_variants(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)
        client_id = await _make_client(session, advisor_id)

        agent_session = AgentSession(
            client_id=client_id,
            agentcore_session_id="runtime-session-roles",
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)

        roles = [
            TurnRole.user,
            TurnRole.assistant,
            TurnRole.system,
            TurnRole.tool,
            TurnRole.error,
        ]
        for idx, role in enumerate(roles):
            session.add(
                AgentTurn(
                    session_id=agent_session.id,
                    turn_index=idx,
                    role=role,
                    actor_kind="human" if role is TurnRole.user else "agent",
                )
            )
        await session.commit()

        rows = (
            await session.execute(
                select(AgentTurn.role)
                .where(AgentTurn.session_id == agent_session.id)
                .order_by(AgentTurn.turn_index)
            )
        ).scalars().all()
        assert rows == roles
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_turn_role_enum_rejects_invalid_variant(session: AsyncSession) -> None:
    """Raw SQL with an unknown enum label must fail with the enum name in the message."""
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)
        client_id = await _make_client(session, advisor_id)

        agent_session = AgentSession(
            client_id=client_id,
            agentcore_session_id="runtime-session-bad-role",
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)

        with pytest.raises(DBAPIError) as excinfo:
            await session.execute(
                text(
                    """
                    insert into public.agent_turns
                        (session_id, turn_index, role, actor_kind)
                    values (:sid, 0, 'not_a_role', 'human')
                    """
                ),
                {"sid": agent_session.id},
            )
            await session.flush()
        assert "turn_role" in str(excinfo.value)
    finally:
        await session.rollback()
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_agent_turn_unique_session_turn_index(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)
        client_id = await _make_client(session, advisor_id)

        agent_session = AgentSession(
            client_id=client_id,
            agentcore_session_id="runtime-session-unique",
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)

        session.add(
            AgentTurn(
                session_id=agent_session.id,
                turn_index=0,
                role=TurnRole.user,
                actor_kind="human",
            )
        )
        await session.commit()

        session.add(
            AgentTurn(
                session_id=agent_session.id,
                turn_index=0,
                role=TurnRole.assistant,
                actor_kind="agent",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    finally:
        await session.rollback()
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_agent_sessions_missing_parent_client_fk(session: AsyncSession) -> None:
    """Orphan AgentSession insert must raise IntegrityError naming the FK."""
    session.add(
        AgentSession(
            client_id=uuid.uuid4(),
            agentcore_session_id="runtime-session-orphan",
        )
    )
    with pytest.raises(IntegrityError) as excinfo:
        await session.commit()
    assert "agent_sessions_client_id_fkey" in str(excinfo.value)
    await session.rollback()


@pytest.mark.asyncio
async def test_rls_posture_agent_tables(session: AsyncSession) -> None:
    """Both tables ship with RLS on and zero policies (D003/S04 posture)."""
    rows = (
        await session.execute(
            text(
                """
                select tablename, rowsecurity
                  from pg_tables
                 where schemaname = 'public'
                   and tablename in ('agent_sessions', 'agent_turns')
                 order by tablename
                """
            )
        )
    ).all()
    rls = {tbl: enabled for tbl, enabled in rows}
    assert rls == {"agent_sessions": True, "agent_turns": True}

    count = (
        await session.execute(
            text(
                """
                select count(*)
                  from pg_policies
                 where schemaname = 'public'
                   and tablename in ('agent_sessions', 'agent_turns')
                """
            )
        )
    ).scalar_one()
    assert count == 0, (
        "agent_sessions and agent_turns must ship with zero policies "
        "(deny-by-default RLS posture)"
    )
