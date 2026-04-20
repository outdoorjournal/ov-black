"""Integration tests for the Client + VoodooDoll SQLAlchemy models.

Mirrors ``tests/test_models.py``: insert through the async engine, read back,
and assert enums coerce, JSONB round-trips preserve structure, and
timestamps arrive tz-aware. Guards against schema drift between
``supabase/migrations/0003_clients_voodoo_dolls.sql`` and the hand-aligned
models in ``app/models/``.

Requires ``supabase start`` (Postgres on port 54322). When the DB is
unreachable the module is skipped — a fresh checkout without Docker should
still run the rest of the suite.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Client, ContactChannel, GroupType, VoodooDoll

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


async def _cleanup(
    session: AsyncSession,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID | None,
) -> None:
    if client_id is not None:
        # voodoo_dolls cascades on clients delete; clients cascades on auth.users.
        await session.execute(
            text("delete from public.clients where id = :id"), {"id": client_id}
        )
    await session.execute(
        text("delete from auth.users where id = :id"), {"id": advisor_id}
    )
    await session.commit()


@pytest.mark.asyncio
async def test_client_round_trip(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)

        client = Client(
            owner_id=advisor_id,
            full_name="Jane Doe",
            email="jane@example.com",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

        fetched = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalar_one()
        assert fetched.owner_id == advisor_id
        assert fetched.auth_user_id is None
        assert fetched.full_name == "Jane Doe"
        assert fetched.email == "jane@example.com"
        assert isinstance(fetched.created_at, datetime)
        assert fetched.created_at.tzinfo is not None
        assert fetched.updated_at.tzinfo is not None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_voodoo_doll_round_trip(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"

    passions = [
        {"label": "wine", "weight": 0.9},
        {"label": "motorsport", "weight": 0.7},
    ]
    motivations = {"primary": "status", "secondary": ["novelty", "wellness"]}
    travel_history = [{"city": "Tokyo", "year": 2024}, {"city": "Lisbon", "year": 2025}]
    triggers = ["crowds", "early mornings"]
    constraints = ["kosher", "no long-haul"]
    deal_breakers = ["budget airlines"]
    dream_trip_signals = {"climate": "temperate", "pace": "slow"}
    osint_notes = {"source": "linkedin", "notes": "board seat at X"}

    try:
        await _insert_auth_user(session, advisor_id, email)

        client = Client(
            owner_id=advisor_id,
            full_name="Jane Doe",
            email="jane@example.com",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

        doll = VoodooDoll(
            client_id=client_id,
            authored_by=advisor_id,
            contact_preference=ContactChannel.whatsapp,
            group_type=GroupType.couple,
            children_ages=[7, 11],
            travel_party_notes="Plus nanny on long trips.",
            estimated_net_worth_usd=25_000_000,
            passions=passions,
            motivations=motivations,
            travel_history=travel_history,
            triggers=triggers,
            constraints=constraints,
            deal_breakers=deal_breakers,
            dream_trip_signals=dream_trip_signals,
            osint_notes=osint_notes,
        )
        session.add(doll)
        await session.commit()

        fetched = (
            await session.execute(
                select(VoodooDoll).where(VoodooDoll.client_id == client_id)
            )
        ).scalar_one()

        # Enums coerce back to the Python enum members (not raw strings).
        assert fetched.contact_preference is ContactChannel.whatsapp
        assert fetched.group_type is GroupType.couple

        # Typed columns round-trip.
        assert fetched.children_ages == [7, 11]
        assert fetched.travel_party_notes == "Plus nanny on long trips."
        assert fetched.estimated_net_worth_usd == 25_000_000

        # JSONB round-trips preserve structure (list-of-dicts, nested dicts).
        assert fetched.passions == passions
        assert fetched.motivations == motivations
        assert fetched.travel_history == travel_history
        assert fetched.triggers == triggers
        assert fetched.constraints == constraints
        assert fetched.deal_breakers == deal_breakers
        assert fetched.dream_trip_signals == dream_trip_signals
        assert fetched.osint_notes == osint_notes

        # Timestamps arrive tz-aware (asyncpg + DateTime(timezone=True)).
        assert isinstance(fetched.created_at, datetime)
        assert fetched.created_at.tzinfo is not None
        assert fetched.updated_at.tzinfo is not None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_voodoo_doll_defaults_round_trip(session: AsyncSession) -> None:
    """Server-side defaults populate JSONB/array columns when omitted."""
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)

        client = Client(
            owner_id=advisor_id,
            full_name="Min Doll Client",
            email="min@example.com",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

        doll = VoodooDoll(
            client_id=client_id,
            authored_by=advisor_id,
            contact_preference=ContactChannel.email,
            group_type=GroupType.solo,
        )
        session.add(doll)
        await session.commit()

        fetched = (
            await session.execute(
                select(VoodooDoll).where(VoodooDoll.client_id == client_id)
            )
        ).scalar_one()

        assert fetched.children_ages == []
        assert fetched.travel_party_notes == ""
        assert fetched.estimated_net_worth_usd is None
        assert fetched.passions == []
        assert fetched.motivations == {}
        assert fetched.travel_history == []
        assert fetched.triggers == []
        assert fetched.constraints == []
        assert fetched.deal_breakers == []
        assert fetched.dream_trip_signals == {}
        assert fetched.osint_notes == {}
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_rls_enabled_on_clients_and_voodoo_dolls(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                """
                select tablename, rowsecurity
                  from pg_tables
                 where schemaname = 'public'
                   and tablename in ('clients', 'voodoo_dolls')
                 order by tablename
                """
            )
        )
    ).all()
    rls = {tbl: enabled for tbl, enabled in rows}
    assert rls == {"clients": True, "voodoo_dolls": True}
