"""Document vault HTTP surfaces — authz matrix + presigned flow (M003/V3).

Integration (gated on local Supabase). Exercises the vault end-to-end through the
real auth stack + DB + the lifespan-wired MockVaultStorage:

- advisor init → complete → download → list,
- traveler self-service,
- cross-advisor 404 collapse + client-role 403,
- the itinerary read-only listing authorized by client access,
- expiry derivation surfaced on the detail shape.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
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
                full_name="Vault Household",
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


def _init_body(**kw: object) -> dict[str, object]:
    body: dict[str, object] = {
        "doc_type": "passport",
        "file_name": "passport.pdf",
        "content_type": "application/pdf",
    }
    body.update(kw)
    return body


# ── advisor surface: init → complete → download → list ───────────────────


def test_advisor_full_presigned_flow(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.advisor_id)
    init = client.post(
        f"/clients/{seed.client_id}/documents",
        headers=h,
        json=_init_body(label="Passport"),
    )
    assert init.status_code == 201, init.text
    body = init.json()
    doc_id = body["document"]["id"]
    assert body["document"]["created_by_actor"] == "advisor"
    assert body["document"]["uploaded_at"] is None
    # Presigned URL is returned, points at the (mock) store, and is not the key.
    assert body["upload_url"].startswith("https://mock-s3.local/")
    assert "s3_key" not in body["document"]

    done = client.post(
        f"/clients/{seed.client_id}/documents/{doc_id}/complete",
        headers=h,
        json={"size_bytes": 4096},
    )
    assert done.status_code == 200, done.text
    assert done.json()["uploaded_at"] is not None

    dl = client.get(f"/clients/{seed.client_id}/documents/{doc_id}/download", headers=h)
    assert dl.status_code == 200
    assert dl.json()["url"].startswith("https://mock-s3.local/")

    listing = client.get(f"/clients/{seed.client_id}/documents", headers=h)
    assert listing.status_code == 200
    assert [d["id"] for d in listing.json()["documents"]] == [doc_id]


def test_advisor_cannot_read_unowned_client_collapses_404(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    resp = client.get(
        f"/clients/{seed.client_id}/documents",
        headers=_hdr(make_token, seed.other_advisor_id),
    )
    assert resp.status_code == 404


def test_client_role_is_forbidden_on_advisor_route(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    resp = client.post(
        f"/clients/{seed.client_id}/documents",
        headers=_hdr(make_token, seed.traveler_id),
        json=_init_body(),
    )
    assert resp.status_code == 403


# ── traveler self-service ────────────────────────────────────────────────


def test_traveler_self_service_init_and_list(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.traveler_id)
    init = client.post("/me/documents", headers=h, json=_init_body(label="Mine"))
    assert init.status_code == 201, init.text
    assert init.json()["document"]["created_by_actor"] == "traveler"

    listing = client.get("/me/documents", headers=h)
    assert listing.status_code == 200
    assert [d["label"] for d in listing.json()["documents"]] == ["Mine"]


def test_expiry_soon_flag_surfaced(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    soon = (date.today() + timedelta(days=30)).isoformat()
    init = client.post(
        "/me/documents",
        headers=_hdr(make_token, seed.traveler_id),
        json=_init_body(expires_at=soon),
    )
    assert init.status_code == 201, init.text
    doc = init.json()["document"]
    assert doc["expired"] is False
    assert doc["expires_soon"] is True


# ── per-trip read-only ───────────────────────────────────────────────────


def test_itinerary_documents_listing_authorized_by_client_access(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    # Seed a document on the household.
    client.post(
        f"/clients/{seed.client_id}/documents",
        headers=_hdr(make_token, seed.advisor_id),
        json=_init_body(label="On trip"),
    )
    # The owning advisor + linked traveler can list the itinerary's docs.
    for sub in (seed.advisor_id, seed.traveler_id):
        resp = client.get(
            f"/itineraries/{seed.itinerary_id}/documents", headers=_hdr(make_token, sub)
        )
        assert resp.status_code == 200, resp.text
        assert [d["label"] for d in resp.json()["documents"]] == ["On trip"]
    # A stranger advisor gets a 404 (no existence leak).
    stranger = client.get(
        f"/itineraries/{seed.itinerary_id}/documents",
        headers=_hdr(make_token, seed.other_advisor_id),
    )
    assert stranger.status_code == 404
