"""Tests for the itinerary approval schema (0006_itinerary_approval.sql).

Two layers, mirroring ``test_itinerary_models.py``:

1. Pure-Python guards — assert the ``ItineraryStatus`` enum values and the
   SAEnum ``create_type=False`` flag so D003 (Supabase CLI owns DDL) doesn't
   regress for the new ``public.itinerary_status`` type.
2. Integration round-trip gated on a locally-running Supabase Postgres. Insert
   a fresh itinerary and assert ``status='draft'`` plus both approval columns
   are NULL — the default pre-approval state for M001's in-flight itineraries.
"""

from __future__ import annotations

import socket
import uuid

import pytest
import pytest_asyncio
from app.models import Itinerary, ItineraryStatus
from app.models.itinerary import itinerary_status_enum
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


def test_itinerary_status_enum_values() -> None:
    """Python enum values must be byte-identical to the Postgres enum.

    Lifecycle draft → proposed (advisor proposes, 0039) → approved.
    """
    assert {m.value for m in ItineraryStatus} == {"draft", "proposed", "approved"}
    assert ItineraryStatus.draft == "draft"
    assert ItineraryStatus.proposed == "proposed"
    assert ItineraryStatus.approved == "approved"


def test_itinerary_status_enum_create_type_is_false() -> None:
    """Regression guard for D003: Supabase CLI owns the CREATE TYPE; SQLAlchemy
    must never emit DDL for ``public.itinerary_status``.
    """
    assert itinerary_status_enum.create_type is False
    assert itinerary_status_enum.name == "itinerary_status"
    assert itinerary_status_enum.schema == "public"


# ── Integration tests (gated on local Supabase) ────────────────────────────

integration = pytest.mark.skipif(
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


async def _cleanup(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    await session.execute(text("delete from public.itineraries where id = :i"), {"i": itinerary_id})
    await session.commit()


@integration
@pytest.mark.asyncio
async def test_freshly_inserted_itinerary_defaults_to_draft(
    session: AsyncSession,
) -> None:
    """A newly-created itinerary row must come back with ``status='draft'``
    and both approval columns NULL — S08 pre-approval invariant.
    """
    itinerary_id = uuid.uuid4()
    try:
        session.add(Itinerary(id=itinerary_id, title="S08 approval default"))
        await session.commit()

        fetched = (
            await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
        ).scalar_one()
        assert fetched.status is ItineraryStatus.draft
        assert fetched.approved_by is None
        assert fetched.approved_at is None
    finally:
        await _cleanup(session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_itinerary_status_column_reports_draft_in_pg_catalog(
    session: AsyncSession,
) -> None:
    """Schema-level sanity check: the status column exists on public.itineraries
    as ``itinerary_status NOT NULL DEFAULT 'draft'``.
    """
    row = (
        await session.execute(
            text(
                """
                select column_name,
                       is_nullable,
                       column_default,
                       udt_schema,
                       udt_name
                  from information_schema.columns
                 where table_schema = 'public'
                   and table_name   = 'itineraries'
                   and column_name  = 'status'
                """
            )
        )
    ).one_or_none()
    assert row is not None, "itineraries.status column is missing"
    column_name, is_nullable, column_default, udt_schema, udt_name = row
    assert column_name == "status"
    assert is_nullable == "NO"
    assert column_default is not None
    assert "draft" in column_default
    assert udt_schema == "public"
    assert udt_name == "itinerary_status"


@integration
@pytest.mark.asyncio
async def test_approval_columns_exist_and_are_nullable(
    session: AsyncSession,
) -> None:
    """approved_by uuid / approved_at timestamptz must be nullable
    and reference auth.users on delete set null (only column-level shape here).
    """
    rows = {
        name: (nullable, dtype)
        for name, nullable, dtype in (
            await session.execute(
                text(
                    """
                    select column_name, is_nullable, data_type
                      from information_schema.columns
                     where table_schema = 'public'
                       and table_name   = 'itineraries'
                       and column_name in ('approved_by', 'approved_at')
                    """
                )
            )
        ).all()
    }
    assert rows["approved_by"] == ("YES", "uuid")
    assert rows["approved_at"][0] == "YES"
    # Postgres reports timestamptz as "timestamp with time zone".
    assert "timestamp" in rows["approved_at"][1]
