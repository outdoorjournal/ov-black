"""Wave F roster pagination — the real /clients and /itineraries endpoints
against the local Supabase (real ILIKE, real keyset predicates, real
needs_attention wiring). Skip without the DB.

The dependency overrides swap only the identity (require_advisor) and the DB
session (bound to LOCAL_DB_URL); the endpoint logic under test runs verbatim.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.main import app as fastapi_app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration


async def _seed_user(s: AsyncSession, uid: uuid.UUID) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"page-{uid}@x.com"},
    )


async def _seed_client(
    s: AsyncSession,
    owner: uuid.UUID,
    *,
    name: str,
    email: str,
    created_at: datetime,
    invited: bool = False,
) -> uuid.UUID:
    cid = uuid.uuid4()
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, full_name, email, created_at, "
            "invited_at) values (:id, :o, :n, :e, :c, :inv)"
        ),
        {
            "id": cid,
            "o": owner,
            "n": name,
            "e": email,
            "c": created_at,
            "inv": created_at if invited else None,
        },
    )
    return cid


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner, stranger = uuid.uuid4(), uuid.uuid4()
    base = datetime.now(UTC)
    async with maker() as s:
        await _seed_user(s, owner)
        await _seed_user(s, stranger)
        names = [
            ("Ada Lovelace", "ada@x.com"),
            ("Blaise Pascal", "blaise@x.com"),
            ("Carl Gauss", "carl@x.com"),
            ("Delia 100% Legit", "delia@x.com"),  # exercises ILIKE escaping
            ("Emmy Noether", "emmy@x.com"),
        ]
        cids = {}
        for i, (name, email) in enumerate(names):
            cids[name] = await _seed_client(
                s,
                owner,
                name=name,
                email=f"page-{uuid.uuid4().hex[:6]}-{email}",
                created_at=base - timedelta(days=i),
                invited=(i % 2 == 0),
            )
        await _seed_client(
            s,
            stranger,
            name="Stranger Person",
            email=f"page-{uuid.uuid4().hex[:6]}-s@x.com",
            created_at=base,
        )
        await s.commit()

        ada_trip = await insert_itinerary(
            s, title="Ada in Kyoto", created_by=owner, client_id=cids["Ada Lovelace"]
        )
        alps_trip = await insert_itinerary(
            s,
            title="Alps ascent",
            created_by=owner,
            client_id=cids["Blaise Pascal"],
        )
        # A pending approvable card puts the Alps trip in the with_traveler
        # bucket; Ada's empty trip derives in_studio.
        await insert_node(s, itinerary_id=alps_trip, type="experience", title="Summit day")
        # An open reconcile on Ada's trip → needs_attention must light.
        await s.execute(
            text("update public.itineraries set reconcile_requested_at = now() where id = :id"),
            {"id": ada_trip},
        )
        await s.commit()
    try:
        yield SimpleNamespace(maker=maker, owner=owner, ada_trip=ada_trip)
    finally:
        await engine.dispose()


@pytest.fixture()
def advisor_identity() -> Iterator[dict[str, Any]]:
    """Mutable holder the override reads — set ``sub`` per test.

    The session override builds a fresh engine *inside the request* so it
    binds to the TestClient's event loop (the fixture world's engine lives on
    the pytest-asyncio loop — sharing it across loops breaks asyncpg).
    """
    holder: dict[str, Any] = {"sub": None}

    async def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            sub=str(holder["sub"]),
            email="advisor@example.com",
            role="authenticated",
            claims={"sub": str(holder["sub"])},
        )

    async def _session() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                yield s
        finally:
            await engine.dispose()

    fastapi_app.dependency_overrides[require_advisor] = _dep
    fastapi_app.dependency_overrides[get_session] = _session
    try:
        yield holder
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)
        fastapi_app.dependency_overrides.pop(get_session, None)


@integration
async def test_clients_search_filters_and_pages(
    advisor_identity: dict[str, Any], make_token: Any
) -> None:
    async with _world() as w:
        advisor_identity["sub"] = w.owner
        headers = {"Authorization": f"Bearer {make_token(sub=str(w.owner))}"}
        with TestClient(fastapi_app) as http:
            # Unfiltered: 5 owned rows, newest-first, stranger invisible.
            body = http.get("/clients", headers=headers).json()
            assert body["total"] == 5
            assert [c["full_name"] for c in body["clients"]][:2] == [
                "Ada Lovelace",
                "Blaise Pascal",
            ]

            # Substring search over name.
            body = http.get("/clients?q=noether", headers=headers).json()
            assert [c["full_name"] for c in body["clients"]] == ["Emmy Noether"]
            assert body["total"] == 1

            # ILIKE wildcards in q stay literal ("100%" must not match all).
            body = http.get("/clients?q=100%25", headers=headers).json()
            assert [c["full_name"] for c in body["clients"]] == ["Delia 100% Legit"]

            # Status filter: seeds alternate invited → 3 pending, 2 uninvited.
            body = http.get("/clients?status=pending", headers=headers).json()
            assert body["total"] == 3
            assert all(c["access_status"] == "pending" for c in body["clients"])

            # Name sort ascends by default.
            body = http.get("/clients?sort=full_name", headers=headers).json()
            names = [c["full_name"] for c in body["clients"]]
            assert names == sorted(names)

            # Cursor walk at page size 2: 5 rows, no dup/skip, total stable.
            walked: list[str] = []
            url = "/clients?limit=2"
            for _ in range(5):
                page = http.get(url, headers=headers).json()
                assert page["total"] == 5
                walked.extend(c["id"] for c in page["clients"])
                if page["next_cursor"] is None:
                    break
                url = f"/clients?limit=2&cursor={page['next_cursor']}"
            assert len(walked) == 5
            assert len(set(walked)) == 5


@integration
async def test_itineraries_search_filters_and_attention(
    advisor_identity: dict[str, Any], make_token: Any
) -> None:
    async with _world() as w:
        advisor_identity["sub"] = w.owner
        headers = {"Authorization": f"Bearer {make_token(sub=str(w.owner))}"}
        with TestClient(fastapi_app) as http:
            body = http.get("/itineraries", headers=headers).json()
            assert body["total"] == 2
            by_id = {r["id"]: r for r in body["itineraries"]}
            # The open reconcile lights Ada's trip and only Ada's trip.
            assert by_id[str(w.ada_trip)]["needs_attention"] is True
            assert sum(1 for r in body["itineraries"] if r["needs_attention"]) == 1

            # q matches the CLIENT name too, not just the title.
            body = http.get("/itineraries?q=pascal", headers=headers).json()
            assert [r["title"] for r in body["itineraries"]] == ["Alps ascent"]

            # Status filter (derived display buckets).
            body = http.get("/itineraries?status=with_traveler", headers=headers).json()
            assert body["total"] == 1
            assert body["itineraries"][0]["status"] == "with_traveler"

            # Cursor pages cleanly at limit=1.
            first = http.get("/itineraries?limit=1", headers=headers).json()
            assert first["next_cursor"] is not None
            second = http.get(
                f"/itineraries?limit=1&cursor={first['next_cursor']}", headers=headers
            ).json()
            ids = {first["itineraries"][0]["id"], second["itineraries"][0]["id"]}
            assert len(ids) == 2
