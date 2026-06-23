"""AI Fill HTTP endpoint + auth gate (Phase 6 / B6).

Integration (gated on local Supabase, via the ``client`` TestClient fixture):
``POST /itinerary/{id}/fill`` — a feasible candidate end-to-end, the
feasibility-unknown path, request validation, 404, 401, and the shared
draft-read gate. The inventory registry is swapped through
``dependency_overrides`` so the endpoint runs against a controlled in-test
provider and never touches live vendors.

Itineraries are seeded directly in the DB (``approved`` skips the draft-read
gate) rather than through ``POST /itinerary`` — the latter stamps
``created_by`` from the JWT ``sub`` and would violate the ``auth.users`` FK for
a synthetic test token (same rationale as the analyze router tests).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from app.inventory.registry import (
    InventoryCtx,
    InventoryProvider,
    InventoryProviderRegistry,
)
from app.inventory.schemas import InventoryItem, Location, MealItem
from app.main import app as fastapi_app
from app.routers.inventory import get_inventory_registry
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import (
    LOCAL_DB_URL,
    insert_itinerary,
    insert_node,
    integration,
    seed_itinerary_sync,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient


_PRIOR = (35.6586, 139.7454)
_NEXT = (35.6595, 139.7004)


def _at(h: int) -> datetime:
    return datetime(2026, 9, 12, h, 0, tzinfo=UTC)


_GAP_BODY = {"gap": {"start": _at(12).isoformat(), "end": _at(18).isoformat()}}


class _FakeProvider(InventoryProvider):
    source = "fake"

    def __init__(self, items: list[InventoryItem]) -> None:
        self._items = items

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        ks = set(kinds) if kinds else None
        return [i for i in self._items if ks is None or i.kind in ks]

    async def get_detail(self, *, source_id: str, ctx: InventoryCtx) -> InventoryItem | None:
        return next((i for i in self._items if i.source_id == source_id), None)


def _meal(source_id: str, lat: float, lng: float) -> MealItem:
    return MealItem(
        source="fake",
        source_id=source_id,
        title=f"Restaurant {source_id}",
        location=Location(lat=lat, lng=lng),
    )


def _override_registry(items: list[InventoryItem]) -> None:
    reg = InventoryProviderRegistry()
    reg.register(_FakeProvider(items))
    fastapi_app.dependency_overrides[get_inventory_registry] = lambda: reg


@pytest.fixture(autouse=True)
def _clear_override() -> Any:
    yield
    fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


def _bearer(make_token: Callable[..., str], sub: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=sub or str(uuid.uuid4()))}"}


def _seed_located_trip_sync() -> uuid.UUID:
    """Seed an approved itinerary with two located + timed Tokyo anchors."""

    async def _seed() -> uuid.UUID:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                iid = await insert_itinerary(s, status="approved")
                await insert_node(
                    s,
                    itinerary_id=iid,
                    type="experience",
                    title="Morning",
                    status="approved",
                    starts_lower=_at(10),
                    starts_upper=_at(12),
                    lat=_PRIOR[0],
                    lng=_PRIOR[1],
                )
                await insert_node(
                    s,
                    itinerary_id=iid,
                    type="experience",
                    title="Evening",
                    status="approved",
                    starts_lower=_at(18),
                    starts_upper=_at(20),
                    lat=_NEXT[0],
                    lng=_NEXT[1],
                )
                return iid
        finally:
            await engine.dispose()

    return asyncio.run(_seed())


@integration
def test_fill_returns_feasible_proposal(client: TestClient, make_token: Callable[..., str]) -> None:
    iid = _seed_located_trip_sync()
    _override_registry([_meal("m-tokyo", 35.67, 139.73)])
    resp = client.post(f"/itinerary/{iid}/fill", json=_GAP_BODY, headers=_bearer(make_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analysis_id"] is None  # none seeded
    assert len(body["proposals"]) >= 1
    top = body["proposals"][0]
    assert top["inventory_source"] == "fake"
    assert top["inventory_id"] == "m-tokyo"
    assert top["type"] == "meal"
    assert top["fits_in_gap"] is True
    assert top["feasibility_unknown"] is False
    assert top["rationale"]
    assert top["location"] == {"lat": 35.67, "lng": 139.73}


@integration
def test_fill_marks_unknown_without_located_anchors(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    # seed_itinerary_sync nodes carry no coordinates/times -> no anchors.
    iid = seed_itinerary_sync()
    _override_registry([_meal("m-tokyo", 35.67, 139.73)])
    resp = client.post(f"/itinerary/{iid}/fill", json=_GAP_BODY, headers=_bearer(make_token))
    assert resp.status_code == 200, resp.text
    proposals = resp.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["feasibility_unknown"] is True
    assert proposals[0]["drive_time_in_min"] is None


@integration
def test_fill_rejects_unknown_field(client: TestClient, make_token: Callable[..., str]) -> None:
    iid = seed_itinerary_sync()
    _override_registry([])
    bad = {**_GAP_BODY, "not_a_field": 1}
    resp = client.post(f"/itinerary/{iid}/fill", json=bad, headers=_bearer(make_token))
    assert resp.status_code == 422  # extra="forbid" surfaces the typo


@integration
def test_fill_unknown_itinerary_404(client: TestClient, make_token: Callable[..., str]) -> None:
    _override_registry([])
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/fill", json=_GAP_BODY, headers=_bearer(make_token)
    )
    assert resp.status_code == 404


@integration
def test_fill_requires_jwt(client: TestClient) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/fill", json=_GAP_BODY)
    assert resp.status_code == 401


@integration
def test_fill_draft_read_gate_forbids_stranger(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    iid = seed_itinerary_sync(status="draft")
    _override_registry([_meal("m-tokyo", 35.67, 139.73)])
    resp = client.post(f"/itinerary/{iid}/fill", json=_GAP_BODY, headers=_bearer(make_token))
    assert resp.status_code == 403
