"""Integration tests for the Client + Dossier + per-fact SQLAlchemy models.

Mirrors ``tests/test_models.py``: insert through the async engine, read back,
and assert enums coerce, JSONB round-trips preserve structure, and
timestamps arrive tz-aware. Guards against schema drift between
``supabase/migrations/0011_dossier_profile_osint.sql`` and the hand-aligned
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

from app.models import (
    Client,
    ContactChannel,
    Dossier,
    DossierFact,
    DossierFactKind,
    FactSourceKind,
    GroupType,
    OsintFact,
    OsintFactKind,
    ProfileFact,
    ProfileFactKind,
)

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
        # Per-fact tables + dossiers cascade on clients delete; clients
        # cascades on auth.users.
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
async def test_dossier_typed_core_round_trip(session: AsyncSession) -> None:
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

        dossier = Dossier(
            client_id=client_id,
            authored_by=advisor_id,
            contact_preference=ContactChannel.whatsapp,
            group_type=GroupType.couple,
            children_ages=[7, 11],
            travel_party_notes="Plus nanny on long trips.",
            estimated_net_worth_usd=25_000_000,
        )
        session.add(dossier)
        await session.commit()

        fetched = (
            await session.execute(
                select(Dossier).where(Dossier.client_id == client_id)
            )
        ).scalar_one()

        # Enums coerce back to the Python enum members.
        assert fetched.contact_preference is ContactChannel.whatsapp
        assert fetched.group_type is GroupType.couple
        # Typed columns round-trip.
        assert fetched.children_ages == [7, 11]
        assert fetched.travel_party_notes == "Plus nanny on long trips."
        assert fetched.estimated_net_worth_usd == 25_000_000
        # Timestamps arrive tz-aware.
        assert isinstance(fetched.created_at, datetime)
        assert fetched.created_at.tzinfo is not None
        assert fetched.updated_at.tzinfo is not None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_dossier_defaults_round_trip(session: AsyncSession) -> None:
    """Server-side defaults populate the array column when omitted."""
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"
    try:
        await _insert_auth_user(session, advisor_id, email)

        client = Client(
            owner_id=advisor_id,
            full_name="Min Dossier Client",
            email="min@example.com",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

        dossier = Dossier(
            client_id=client_id,
            authored_by=advisor_id,
            contact_preference=ContactChannel.email,
            group_type=GroupType.solo,
        )
        session.add(dossier)
        await session.commit()

        fetched = (
            await session.execute(
                select(Dossier).where(Dossier.client_id == client_id)
            )
        ).scalar_one()

        assert fetched.children_ages == []
        assert fetched.travel_party_notes == ""
        assert fetched.estimated_net_worth_usd is None
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_per_fact_round_trip_for_all_three_tiers(session: AsyncSession) -> None:
    advisor_id = uuid.uuid4()
    client_id: uuid.UUID | None = None
    email = f"advisor-{advisor_id.hex[:8]}@example.com"

    try:
        await _insert_auth_user(session, advisor_id, email)

        client = Client(
            owner_id=advisor_id,
            full_name="Multi-tier Client",
            email="multi@example.com",
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)
        client_id = client.id

        # One fact per tier.
        session.add(
            DossierFact(
                client_id=client_id,
                kind=DossierFactKind.passion,
                text="loves heli-skiing",
                source_kind=FactSourceKind.advisor,
                source_ref={"note": "from intake"},
                recorded_by=advisor_id,
            )
        )
        session.add(
            ProfileFact(
                client_id=client_id,
                kind=ProfileFactKind.preference,
                text="morning starts",
                source_kind=FactSourceKind.advisor,
                source_ref={},
                recorded_by=advisor_id,
            )
        )
        session.add(
            OsintFact(
                client_id=client_id,
                kind=OsintFactKind.linkedin,
                text="CFO at Acme",
                source_kind=FactSourceKind.advisor,
                source_ref={"url": "https://example.com"},
                recorded_by=advisor_id,
            )
        )
        await session.commit()

        d = (
            await session.execute(
                select(DossierFact).where(DossierFact.client_id == client_id)
            )
        ).scalar_one()
        p = (
            await session.execute(
                select(ProfileFact).where(ProfileFact.client_id == client_id)
            )
        ).scalar_one()
        o = (
            await session.execute(
                select(OsintFact).where(OsintFact.client_id == client_id)
            )
        ).scalar_one()

        assert d.kind is DossierFactKind.passion
        assert d.source_kind is FactSourceKind.advisor
        assert d.source_ref == {"note": "from intake"}
        assert d.redacted_at is None

        assert p.kind is ProfileFactKind.preference
        assert p.source_kind is FactSourceKind.advisor

        assert o.kind is OsintFactKind.linkedin
        assert o.source_ref == {"url": "https://example.com"}
    finally:
        await _cleanup(session, advisor_id, client_id)


@pytest.mark.asyncio
async def test_rls_enabled_on_clients_and_fact_tables(session: AsyncSession) -> None:
    rows = (
        await session.execute(
            text(
                """
                select tablename, rowsecurity
                  from pg_tables
                 where schemaname = 'public'
                   and tablename in (
                       'clients', 'dossiers',
                       'dossier_facts', 'profile_facts', 'osint_facts'
                   )
                 order by tablename
                """
            )
        )
    ).all()
    rls = {tbl: enabled for tbl, enabled in rows}
    assert rls == {
        "clients": True,
        "dossiers": True,
        "dossier_facts": True,
        "profile_facts": True,
        "osint_facts": True,
    }
