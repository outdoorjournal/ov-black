"""Integration tests for the SQLAlchemy models against a live Postgres.

These tests insert + select through the async engine so a schema drift between
``supabase/migrations/0001_init.sql`` and the hand-aligned models in
``app/models/`` fails loudly. They also verify RLS is enabled with the
expected policy shape by querying ``pg_policies`` / ``pg_tables``.

The tests require ``supabase start`` to be running locally (Postgres on
port 54322). When the DB is unreachable we skip rather than fail — a dev
machine without Docker should be able to run the rest of the suite.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Invite, Profile, UserRole

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
    # Function-scoped engine so each test gets a connection bound to the
    # per-test asyncio loop (pytest-asyncio default). Spinning up an engine
    # per test is cheap — the local Supabase instance handles it easily.
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _insert_auth_user(session: AsyncSession, user_id: uuid.UUID, email: str) -> None:
    """Create a minimal auth.users row so FK-backed inserts succeed.

    Supabase's auth schema has many NOT NULL columns with server defaults and
    triggers — we rely on those defaults and only set id + email explicitly.
    """
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


async def _cleanup(session: AsyncSession, user_id: uuid.UUID, invite_code: str | None) -> None:
    if invite_code is not None:
        await session.execute(
            text("delete from public.invites where code = :c"), {"c": invite_code}
        )
    await session.execute(text("delete from auth.users where id = :id"), {"id": user_id})
    await session.commit()


@pytest.mark.asyncio
async def test_profile_round_trip(session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    email = f"roundtrip-{user_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, user_id, email)
        profile = Profile(id=user_id, role=UserRole.advisor)
        session.add(profile)
        await session.commit()

        fetched = (
            await session.execute(select(Profile).where(Profile.id == user_id))
        ).scalar_one()
        assert fetched.id == user_id
        assert fetched.role is UserRole.advisor
        assert isinstance(fetched.created_at, datetime)
        assert fetched.created_at.tzinfo is not None  # timestamptz
    finally:
        await session.execute(
            text("delete from public.profiles where id = :id"), {"id": user_id}
        )
        await _cleanup(session, user_id, None)


@pytest.mark.asyncio
async def test_invite_round_trip(session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    email = f"inviter-{user_id.hex[:8]}@example.com"
    code = f"INV-{uuid.uuid4().hex[:10].upper()}"
    try:
        await _insert_auth_user(session, user_id, email)
        invite = Invite(
            code=code,
            role=UserRole.client,
            email="guest@example.com",
            created_by=user_id,
        )
        session.add(invite)
        await session.commit()

        fetched = (
            await session.execute(select(Invite).where(Invite.code == code))
        ).scalar_one()
        assert fetched.code == code
        assert fetched.role is UserRole.client
        assert fetched.email == "guest@example.com"
        assert fetched.consumed_at is None
        assert fetched.created_by == user_id
        assert isinstance(fetched.created_at, datetime)

        # Mark consumed — exercise the nullable → timestamptz transition.
        now = datetime.now(timezone.utc)
        fetched.consumed_at = now
        await session.commit()
        await session.refresh(fetched)
        assert fetched.consumed_at is not None
        assert fetched.consumed_at.tzinfo is not None
    finally:
        await _cleanup(session, user_id, code)


@pytest.mark.asyncio
async def test_rls_enabled_on_profiles_and_invites(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                """
                select tablename, rowsecurity
                  from pg_tables
                 where schemaname = 'public'
                   and tablename in ('profiles', 'invites')
                 order by tablename
                """
            )
        )
    ).all()
    rls = {tbl: enabled for tbl, enabled in rows}
    assert rls == {"invites": True, "profiles": True}


@pytest.mark.asyncio
async def test_profiles_owner_select_policy_shape(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                """
                select policyname, cmd, roles
                  from pg_policies
                 where schemaname = 'public'
                   and tablename  = 'profiles'
                   and policyname = 'profiles_owner_select'
                """
            )
        )
    ).one()
    policyname, cmd, roles = row
    assert policyname == "profiles_owner_select"
    assert cmd == "SELECT"
    assert "authenticated" in roles


@pytest.mark.asyncio
async def test_invites_has_no_policies_service_role_only(session: AsyncSession) -> None:
    count = (
        await session.execute(
            text(
                "select count(*) from pg_policies where schemaname='public' and tablename='invites'"
            )
        )
    ).scalar_one()
    # RLS enabled + zero policies = deny-by-default for anon/authenticated;
    # service_role bypasses RLS. This is the contract T05 depends on.
    assert count == 0
