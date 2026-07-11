"""Export + day-notes HTTP surface — authz, content types, day-notes CRUD.

Integration (gated on local Supabase). Exercises the real auth stack + DB.
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

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi.testclient import TestClient

pytestmark = integration

_PDF = "application/pdf"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class _Seed:
    advisor_id: uuid.UUID
    traveler_id: uuid.UUID
    other_traveler_id: uuid.UUID
    client_id: uuid.UUID
    itinerary_id: uuid.UUID
    foreign_fork_id: uuid.UUID


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
            traveler_id = uuid.uuid4()
            other_traveler_id = uuid.uuid4()
            await _insert_auth_user(s, advisor_id, f"adv-{advisor_id.hex[:8]}@x.com")
            await _insert_auth_user(s, traveler_id, f"trv-{traveler_id.hex[:8]}@x.com")
            await _insert_auth_user(s, other_traveler_id, f"trv2-{other_traveler_id.hex[:8]}@x.com")
            s.add_all(
                [
                    Profile(id=advisor_id, role=UserRole.advisor),
                    Profile(id=traveler_id, role=UserRole.client),
                    Profile(id=other_traveler_id, role=UserRole.client),
                ]
            )
            client = Client(
                owner_id=advisor_id,
                auth_user_id=traveler_id,
                full_name="Export Household",
                email=f"head-{advisor_id.hex[:8]}@x.com",
            )
            s.add(client)
            await s.commit()
            await s.refresh(client)
            iid = await insert_itinerary(s, client_id=client.id)
            await insert_node(
                s,
                itinerary_id=iid,
                type="experience",
                title="Temple visit",
                starts_lower=None,
                cost_amount=100.0,
                cost_currency="USD",
            )
            # A fork created by the OTHER traveler — the household traveler and a
            # non-advisor must not read it.
            fork_id = await insert_itinerary(
                s, client_id=client.id, forked_from_id=iid, created_by=other_traveler_id
            )
            return _Seed(advisor_id, traveler_id, other_traveler_id, client.id, iid, fork_id)
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
            ids = [seed.advisor_id, seed.traveler_id, seed.other_traveler_id]
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


# ── Export download ──────────────────────────────────────────────────────────


def test_export_pdf_and_xlsx_for_traveler(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.traveler_id)
    pdf = client.get(f"/itinerary/{seed.itinerary_id}/export?format=pdf", headers=h)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == _PDF
    assert pdf.content[:4] == b"%PDF"
    assert "attachment" in pdf.headers["content-disposition"]
    assert ".pdf" in pdf.headers["content-disposition"]

    xlsx = client.get(f"/itinerary/{seed.itinerary_id}/export?format=xlsx", headers=h)
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"] == _XLSX
    assert xlsx.content[:2] == b"PK"
    assert ".xlsx" in xlsx.headers["content-disposition"]


def test_export_advisor_can_download(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.advisor_id)
    resp = client.get(f"/itinerary/{seed.itinerary_id}/export?format=pdf", headers=h)
    assert resp.status_code == 200


def test_export_unknown_itinerary_404(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.advisor_id)
    resp = client.get(f"/itinerary/{uuid.uuid4()}/export?format=pdf", headers=h)
    assert resp.status_code == 404


def test_export_bad_format_422(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    h = _hdr(make_token, seed.traveler_id)
    resp = client.get(f"/itinerary/{seed.itinerary_id}/export?format=docx", headers=h)
    assert resp.status_code == 422


def test_export_foreign_fork_forbidden(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    # The household traveler cannot read another user's private fork.
    h = _hdr(make_token, seed.traveler_id)
    resp = client.get(f"/itinerary/{seed.foreign_fork_id}/export?format=pdf", headers=h)
    assert resp.status_code == 403


# ── Day-notes CRUD ───────────────────────────────────────────────────────────


def test_day_notes_advisor_crud_and_traveler_read(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    adv = _hdr(make_token, seed.advisor_id)
    trav = _hdr(make_token, seed.traveler_id)
    day = "2026-06-01"

    put = client.put(
        f"/itinerary/{seed.itinerary_id}/day-notes/{day}",
        headers=adv,
        json={"bring": ["Camera"], "tips": ["Nap on arrival"]},
    )
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "advisor"
    assert put.json()["content"]["bring"] == ["Camera"]

    listing = client.get(f"/itinerary/{seed.itinerary_id}/day-notes", headers=trav)
    assert listing.status_code == 200
    notes = listing.json()["notes"]
    assert len(notes) == 1
    assert notes[0]["day_date"] == day

    delete = client.delete(f"/itinerary/{seed.itinerary_id}/day-notes/{day}", headers=adv)
    assert delete.status_code == 204
    after = client.get(f"/itinerary/{seed.itinerary_id}/day-notes", headers=trav)
    assert after.json()["notes"] == []


def test_day_notes_traveler_cannot_write(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    trav = _hdr(make_token, seed.traveler_id)
    put = client.put(
        f"/itinerary/{seed.itinerary_id}/day-notes/2026-06-01",
        headers=trav,
        json={"bring": ["x"], "tips": []},
    )
    assert put.status_code == 403
    gen = client.post(
        f"/itinerary/{seed.itinerary_id}/day-notes/generate", headers=trav, json={}
    )
    assert gen.status_code == 403


def test_day_notes_generate_409_when_disabled(
    client: TestClient, make_token: Callable[..., str], seed: _Seed
) -> None:
    # export_day_notes_enabled defaults False in tests → manual invoke 409s.
    adv = _hdr(make_token, seed.advisor_id)
    gen = client.post(
        f"/itinerary/{seed.itinerary_id}/day-notes/generate", headers=adv, json={}
    )
    assert gen.status_code == 409
    assert gen.json()["detail"] == "day_notes_disabled"
