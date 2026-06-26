"""Party member HTTP surfaces — authz matrix (M003/V1).

Integration (gated on local Supabase). Exercises the three collaborative
surfaces end-to-end through the real auth stack + DB:

- advisor ``/clients/{id}/party-members`` (require_advisor + owner scoping),
- the cross-advisor 404 collapse (no existence leak),
- the client-role 403 on the advisor route,
- traveler ``/me/party-members`` self-service (resolved from the JWT),
- per-trip attach authorized by access to the itinerary's client.

Identities are seeded directly (auth.users + profiles + clients) so a synthetic
JWT ``sub`` resolves through ``require_advisor`` / ``resolve_client_for_auth_user``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from app.models import Client, Profile, UserRole
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi.testclient import TestClient

pytestmark = integration


@dataclass
class _Seed:
    advisor_id: uuid.UUID
    other_advisor_id: uuid.UUID
    traveler_id: uuid.UUID
    client_id: uuid.UUID
    itinerary_id: uuid.UUID


async def _insert_auth_user(s: AsyncSession, uid: uuid.UUID, email: str) -> None:
    await s.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": uid, "email": email},
    )


async def _seed_async() -> _Seed:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            advisor_id = uuid.uuid4()
            other_advisor_id = uuid.uuid4()
            traveler_id = uuid.uuid4()
            await _insert_auth_user(s, advisor_id, f"adv-{advisor_id.hex[:8]}@example.com")
            await _insert_auth_user(s, other_advisor_id, f"adv2-{other_advisor_id.hex[:8]}@x.com")
            await _insert_auth_user(s, traveler_id, f"trv-{traveler_id.hex[:8]}@example.com")
            s.add_all(
                [
                    Profile(id=advisor_id, role=UserRole.advisor),
                    Profile(id=other_advisor_id, role=UserRole.advisor),
                    Profile(id=traveler_id, role=UserRole.client),
                ]
            )
            client = Client(
                owner_id=advisor_id,
                auth_user_id=traveler_id,
                full_name="Household Head",
                email=f"head-{advisor_id.hex[:8]}@example.com",
            )
            s.add(client)
            await s.commit()
            await s.refresh(client)
            iid = await insert_itinerary(s, client_id=client.id)
            return _Seed(advisor_id, other_advisor_id, traveler_id, client.id, iid)
    finally:
        await engine.dispose()


async def _cleanup_async(seed: _Seed) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            await s.execute(
                text("delete from public.itineraries where client_id = :cid"),
                {"cid": seed.client_id},
            )
            await s.execute(
                text("delete from public.clients where id = :cid"), {"cid": seed.client_id}
            )
            ids = [seed.advisor_id, seed.other_advisor_id, seed.traveler_id]
            await s.execute(text("delete from public.profiles where id = any(:ids)"), {"ids": ids})
            await s.execute(text("delete from auth.users where id = any(:ids)"), {"ids": ids})
            await s.commit()
    finally:
        await engine.dispose()


@pytest.fixture()
def seed() -> Iterator[_Seed]:
    s = asyncio.run(_seed_async())
    try:
        yield s
    finally:
        asyncio.run(_cleanup_async(s))


def _hdr(make_token: Callable[..., str], sub: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(sub))}"}


# ── advisor surface ──────────────────────────────────────────────────────


def test_advisor_creates_and_lists_member(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.advisor_id)
    created = client.post(
        f"/clients/{seed.client_id}/party-members",
        headers=h,
        json={"full_name": "Avery", "dietary": "no shellfish", "is_primary": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["created_by_actor"] == "advisor"

    listing = client.get(f"/clients/{seed.client_id}/party-members", headers=h)
    assert listing.status_code == 200
    members = listing.json()["members"]
    assert [m["full_name"] for m in members] == ["Avery"]


def test_advisor_cannot_read_unowned_client_collapses_404(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    # A different advisor must not even learn the client exists.
    resp = client.get(
        f"/clients/{seed.client_id}/party-members",
        headers=_hdr(make_token, seed.other_advisor_id),
    )
    assert resp.status_code == 404


def test_client_role_is_forbidden_on_advisor_route(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    resp = client.post(
        f"/clients/{seed.client_id}/party-members",
        headers=_hdr(make_token, seed.traveler_id),  # role=client in profiles
        json={"full_name": "Nope"},
    )
    assert resp.status_code == 403


# ── traveler self-service ────────────────────────────────────────────────


def test_traveler_self_service_create_and_list(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.traveler_id)
    created = client.post(
        "/me/party-members", headers=h, json={"full_name": "My Spouse", "dietary": "vegan"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["created_by_actor"] == "traveler"

    listing = client.get("/me/party-members", headers=h)
    assert listing.status_code == 200
    assert [m["full_name"] for m in listing.json()["members"]] == ["My Spouse"]


# ── per-trip attach ──────────────────────────────────────────────────────


def test_attach_member_to_itinerary_authorized_by_client_access(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    advisor = _hdr(make_token, seed.advisor_id)
    member = client.post(
        f"/clients/{seed.client_id}/party-members", headers=advisor, json={"full_name": "Trip Goer"}
    ).json()

    # An unrelated advisor can't attach onto this itinerary (404, no leak).
    stranger = client.post(
        f"/itineraries/{seed.itinerary_id}/party/members",
        headers=_hdr(make_token, seed.other_advisor_id),
        json={"party_member_id": member["id"]},
    )
    assert stranger.status_code == 404

    attached = client.post(
        f"/itineraries/{seed.itinerary_id}/party/members",
        headers=advisor,
        json={"party_member_id": member["id"]},
    )
    assert attached.status_code == 201, attached.text
    body = attached.json()
    assert body["itinerary_id"] == str(seed.itinerary_id)
    assert [m["party_member_id"] for m in body["members"]] == [member["id"]]
