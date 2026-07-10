"""Raw-SQL graph seeding helpers for the Analyze integration tests.

Mirrors the per-file raw-SQL setup used by ``test_timeline_service.py`` /
``test_node_cost.py`` (writes bypass the service layer so the Phase 1/4 columns
— ``starts_at``, ``location``, ``status``, ``cost_*`` — are exercised straight
through). Factored into one module because three Analyze test files need the
same inserts.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
_LOCAL_HOST = "127.0.0.1"
_LOCAL_PORT = 54322


def supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((_LOCAL_HOST, _LOCAL_PORT))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


async def insert_itinerary(
    session: AsyncSession,
    *,
    title: str = "Analyze test trip",
    created_by: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    forked_from_id: uuid.UUID | None = None,
    fork_status: str | None = None,
) -> uuid.UUID:
    iid = uuid.uuid4()
    if forked_from_id is not None and fork_status is None:
        fork_status = "open"
    await session.execute(
        text(
            """
            insert into public.itineraries
              (id, title, created_by, client_id, forked_from_id, fork_status)
            values
              (:id, :t, :cb, :cid, :ffi, cast(:fs as public.fork_status))
            """
        ),
        {
            "id": iid,
            "t": title,
            "cb": created_by,
            "cid": client_id,
            "ffi": forked_from_id,
            "fs": fork_status,
        },
    )
    await session.commit()
    return iid


async def insert_node(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    type: str,
    title: str = "",
    status: str = "pending",
    starts_lower: datetime | None = None,
    starts_upper: datetime | None = None,
    lat: float | None = None,
    lng: float | None = None,
    cost_amount: float | None = None,
    cost_currency: str | None = None,
    is_selected_alt: bool = True,
    role: str | None = None,
) -> uuid.UUID:
    nid = uuid.uuid4()
    # cost amount⇔currency must travel together (nodes_cost_amount_currency_together).
    if cost_amount is not None and cost_currency is None:
        cost_currency = "USD"
    await session.execute(
        text(
            """
            insert into public.nodes
              (id, itinerary_id, type, title, status, is_selected_alt, role,
               starts_at, location, cost_amount, cost_currency)
            values (
              :id, :iid, cast(:type as public.node_type), :title,
              cast(:status as public.node_status), :sel,
              cast(:role as public.node_role),
              case when cast(:lo as timestamptz) is null
                        and cast(:hi as timestamptz) is null then null
                   else tstzrange(
                       cast(:lo as timestamptz), cast(:hi as timestamptz), '[)'
                   ) end,
              case when cast(:lat as double precision) is null then null
                   else st_setsrid(
                       st_makepoint(
                           cast(:lng as double precision),
                           cast(:lat as double precision)
                       ), 4326
                   )::geography end,
              cast(:cost_amount as numeric), :cost_currency
            )
            """
        ),
        {
            "id": nid,
            "iid": itinerary_id,
            "type": type,
            "title": title,
            "status": status,
            "sel": is_selected_alt,
            "role": role,
            "lo": starts_lower,
            "hi": starts_upper,
            "lat": lat,
            "lng": lng,
            "cost_amount": cost_amount,
            "cost_currency": cost_currency,
        },
    )
    await session.commit()
    return nid


def seed_itinerary_sync(
    *,
    node_titles: tuple[str, ...] = ("Museum", "Lunch"),
    created_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Seed an itinerary + plain nodes from a SYNC test (TestClient-based).

    Runs the async inserts on a throwaway engine via ``asyncio.run`` so sync
    router tests can prepare real DB rows. The read gate is topology-derived
    now: a trunk is readable by its owning client, its creator, or an advisor
    — pass ``created_by`` matching the caller's auth user id to make it
    readable by a non-advisor, or leave it None for a row only advisors can
    read.
    """

    async def _seed() -> uuid.UUID:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                iid = await insert_itinerary(s, created_by=created_by)
                for t in node_titles:
                    await insert_node(s, itinerary_id=iid, type="experience", title=t)
                return iid
        finally:
            await engine.dispose()

    return asyncio.run(_seed())


def seed_auth_user_sync() -> uuid.UUID:
    """Insert a minimal ``auth.users`` row (fresh engine) and return its id.

    The topology-derived read gate admits a trunk's creator, so router tests
    that need a non-advisor caller with read access seed a real auth user,
    mint the JWT with that sub, and stamp it as ``created_by``.
    """

    async def _seed() -> uuid.UUID:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        uid = uuid.uuid4()
        try:
            async with maker() as s:
                await s.execute(
                    text(
                        "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                        "values (:id, :email, false, false)"
                    ),
                    {"id": uid, "email": f"seed-{uid}@test.local"},
                )
                await s.commit()
                return uid
        finally:
            await engine.dispose()

    return asyncio.run(_seed())


async def insert_edge(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    from_node_id: uuid.UUID,
    to_node_id: uuid.UUID,
    type: str = "follows",
) -> uuid.UUID:
    eid = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into public.edges
              (id, itinerary_id, from_node_id, to_node_id, type)
            values
              (:id, :iid, :f, :t, cast(:ty as public.edge_type))
            """
        ),
        {"id": eid, "iid": itinerary_id, "f": from_node_id, "t": to_node_id, "ty": type},
    )
    await session.commit()
    return eid
