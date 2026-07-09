"""Router-level coverage for GET /search-inventory + GET /inventory/{source}/{source_id}.

Approach: stand up an in-memory ``InventoryProviderRegistry`` populated
with two hand-built fake providers (one impersonating OV, one
impersonating Mock). Override ``get_inventory_registry`` via FastAPI
``dependency_overrides`` so the real lifespan-wired registry is never
touched. Every test re-parses the response items through
``TypeAdapter[list[InventoryItem]]`` — the slice-acceptance "same shape"
condition — so a provider drift that returns raw dicts would fail the
discriminated-union validation here instead of silently leaking.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from app.inventory.registry import (
    InventoryCtx,
    InventoryProvider,
    InventoryProviderRegistry,
)
from app.inventory.schemas import (
    DestinationItem,
    ExperienceItem,
    InventoryItem,
    Location,
    Price,
    Range,
)
from app.main import app as fastapi_app
from app.routers.inventory import get_inventory_registry
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Callable


_ITEMS_ADAPTER: TypeAdapter[list[InventoryItem]] = TypeAdapter(list[InventoryItem])


# ── Fake providers ─────────────────────────────────────────────────────────


class FakeOVProvider(InventoryProvider):
    """OV-shaped provider returning a static ExperienceItem list."""

    source = "ov"

    def __init__(self, items: list[InventoryItem]) -> None:
        self._items = items
        self.search_calls: list[dict[str, Any]] = []
        self.detail_calls: list[dict[str, Any]] = []

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        self.search_calls.append(
            {"kinds": kinds, "keyword": keyword, "filters": dict(filters), "ctx": ctx}
        )
        if not keyword:
            return list(self._items)
        needle = keyword.casefold()
        return [i for i in self._items if needle in i.title.casefold()]

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        self.detail_calls.append({"source_id": source_id, "ctx": ctx})
        for item in self._items:
            if item.source_id == source_id:
                return item
        return None


class FakeMockProvider(FakeOVProvider):
    source = "mock"


class FakeBrokenProvider(InventoryProvider):
    """Provider whose search always raises — the diagnostics-capture case."""

    source = "broken"

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict,
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        raise RuntimeError("upstream exploded")

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        return None


# ── Test fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def ov_items() -> list[InventoryItem]:
    return [
        ExperienceItem(
            source="ov",
            source_id="ov-como-1",
            title="Como Lake Hike",
            description="Alpine ridges above Lake Como.",
            photos=["https://example.com/ov/como1.jpg"],
            location=Location(lat=46.0, lng=9.25, label="Como, Italy"),
            price=Price(amount_min=110.0, amount_max=110.0, currency="USD"),
            tags=["hiking", "alpine"],
            duration_days=Range(min=3, max=5),
        ),
        ExperienceItem(
            source="ov",
            source_id="ov-amalfi-1",
            title="Amalfi Coast Walk",
            tags=["coastal"],
        ),
    ]


@pytest.fixture()
def mock_items() -> list[InventoryItem]:
    return [
        DestinationItem(
            source="mock",
            source_id="mock-como-dest",
            title="Como Region",
            description="Lakes and mountains of northern Italy.",
            tags=["unesco"],
        ),
        DestinationItem(
            source="mock",
            source_id="mock-rome",
            title="Rome",
            tags=[],
        ),
    ]


@pytest.fixture()
def fake_registry(
    ov_items: list[InventoryItem],
    mock_items: list[InventoryItem],
) -> InventoryProviderRegistry:
    registry = InventoryProviderRegistry()
    registry.register(FakeOVProvider(ov_items))
    registry.register(FakeMockProvider(mock_items))
    return registry


@pytest.fixture()
def override_registry(fake_registry: InventoryProviderRegistry):
    def _dep() -> InventoryProviderRegistry:
        return fake_registry

    fastapi_app.dependency_overrides[get_inventory_registry] = _dep
    try:
        yield fake_registry
    finally:
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


# ── JWT inheritance ────────────────────────────────────────────────────────


def test_search_inventory_requires_jwt(
    client: TestClient, override_registry: InventoryProviderRegistry
) -> None:
    # Slice acceptance: proves the new routes inherit JWT middleware
    # automatically because they sit outside PUBLIC_PATHS.
    resp = client.get("/search-inventory?keyword=como")
    assert resp.status_code == 401


def test_inventory_detail_requires_jwt(
    client: TestClient, override_registry: InventoryProviderRegistry
) -> None:
    resp = client.get("/inventory/ov/ov-como-1")
    assert resp.status_code == 401


def test_inventory_routes_not_in_public_paths() -> None:
    from app.auth import PUBLIC_PATHS

    for p in PUBLIC_PATHS:
        assert not p.startswith("/search-inventory")
        assert not p.startswith("/inventory/")


# ── Aggregate vs single-source scope ──────────────────────────────────────


def test_search_no_source_aggregates_both_providers(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    sources = {item["source"] for item in body["items"]}
    assert sources == {"ov", "mock"}
    assert body["count"] == len(body["items"])
    # Re-parse through the discriminated union — drift in shape would fail here.
    _ITEMS_ADAPTER.validate_python(body["items"])


def test_search_source_ov_returns_only_ov_items(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all(i["source"] == "ov" for i in items)
    _ITEMS_ADAPTER.validate_python(items)


def test_search_source_mock_returns_mock_items_in_same_shape(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # Slice-plan demo: a mock-scoped call returns fixture items in the
    # SAME InventoryItem shape as OV — validated by re-parsing.
    resp = client.get("/search-inventory?source=mock", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all(i["source"] == "mock" for i in items)
    parsed = _ITEMS_ADAPTER.validate_python(items)
    # Discriminator must be honored end-to-end.
    for item in parsed:
        assert item.kind in {
            "experience",
            "destination",
            "hotel",
            "flight",
            "meal",
            "transit",
            "note",
        }


def test_search_unknown_source_returns_400(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=banana", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unknown_source"


def test_search_empty_sources_treated_as_aggregate(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # No ``source`` param at all — FastAPI parses it as None (the aggregate
    # path). Both providers are hit.
    resp = client.get("/search-inventory", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    sources = {item["source"] for item in body["items"]}
    assert sources == {"ov", "mock"}


def test_search_missing_keyword_is_allowed(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # Empty keyword must not 4xx — the slice plan spec says missing
    # keyword is a valid "list everything" request.
    resp = client.get("/search-inventory?source=ov", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1


# ── Limit cap ──────────────────────────────────────────────────────────────


def test_search_oversized_limit_is_capped_server_side(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # Load-profile protection: the 10x breakpoint is bounded at 50.
    resp = client.get("/search-inventory?source=ov&limit=1000", headers=auth_headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    assert provider.search_calls[-1]["filters"]["limit"] == 50


def test_search_small_limit_is_passed_through(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=ov&limit=5", headers=auth_headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    assert provider.search_calls[-1]["filters"]["limit"] == 5


def test_search_zero_limit_rejected_by_validation(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # ge=1 on the Query means ``limit=0`` is a 422, not a silent no-op.
    resp = client.get("/search-inventory?source=ov&limit=0", headers=auth_headers)
    assert resp.status_code == 422


# ── Flight-search params → filters ─────────────────────────────────────────


def test_search_forwards_flight_params_into_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # The flight (Duffel) route + date + cabin ride in ``filters``; providers
    # that don't consume them ignore the extra keys.
    resp = client.get(
        "/search-inventory?source=ov&origin=LHR&destination=JFK"
        "&departure_date=2026-07-12&return_date=2026-07-20"
        "&cabin_class=business&adults=2",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    assert filters["origin"] == "LHR"
    assert filters["destination"] == "JFK"
    assert filters["departure_date"] == "2026-07-12"
    assert filters["return_date"] == "2026-07-20"
    assert filters["cabin_class"] == "business"
    assert filters["adults"] == 2


def test_search_omits_unset_flight_params_from_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # A plain keyword search must not inject empty flight keys into filters.
    resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    for key in ("origin", "destination", "departure_date", "return_date", "cabin_class", "adults"):
        assert key not in filters


# ── Hotel-search params → filters ──────────────────────────────────────────


def test_search_forwards_hotel_params_into_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # The hotel (Ratehawk) location + dates ride in ``filters``; providers
    # that don't consume them ignore the extra keys.
    resp = client.get(
        "/search-inventory?source=ov&region_id=2381"
        "&checkin=2026-09-12&checkout=2026-09-14"
        "&adults=2&residency=us&currency=USD",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    assert filters["region_id"] == 2381
    assert filters["checkin"] == "2026-09-12"
    assert filters["checkout"] == "2026-09-14"
    assert filters["adults"] == 2
    assert filters["residency"] == "us"
    assert filters["currency"] == "USD"


def test_search_forwards_hotel_geo_params_into_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get(
        "/search-inventory?source=ov&latitude=45.98&longitude=9.25"
        "&checkin=2026-09-12&checkout=2026-09-14",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    assert filters["latitude"] == 45.98
    assert filters["longitude"] == 9.25


def test_search_omits_unset_hotel_params_from_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    for key in (
        "region_id",
        "latitude",
        "longitude",
        "checkin",
        "checkout",
        "residency",
        "currency",
    ):
        assert key not in filters


# ── Places location-bias params → filters ──────────────────────────────────


def test_search_forwards_places_location_bias_into_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # The Google Places location bias rides in ``filters`` under near_* keys
    # (distinct from the Ratehawk hotel-geo latitude/longitude).
    resp = client.get(
        "/search-inventory?source=ov&kinds=meal&keyword=sushi"
        "&near_lat=35.66&near_lng=139.73&radius_m=1200",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    assert filters["near_lat"] == 35.66
    assert filters["near_lng"] == 139.73
    assert filters["radius_m"] == 1200


def test_search_omits_unset_places_params_from_filters(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    filters = provider.search_calls[-1]["filters"]
    for key in ("near_lat", "near_lng", "radius_m"):
        assert key not in filters


# ── Actor context threading ────────────────────────────────────────────────


def test_search_forwards_actor_context_from_user(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    make_token: Callable[..., str],
) -> None:
    sub = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {make_token(sub=sub)}"}
    resp = client.get("/search-inventory?source=ov", headers=headers)
    assert resp.status_code == 200
    provider = override_registry.get("ov")
    assert isinstance(provider, FakeOVProvider)
    ctx = provider.search_calls[-1]["ctx"]
    assert ctx.actor_kind == "user"
    assert ctx.actor_id == sub


# ── Per-provider diagnostics ───────────────────────────────────────────────


def test_search_response_includes_per_source_diagnostics(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    by_source = {d["source"]: d for d in body["sources"]}
    assert set(by_source) == {"ov", "mock"}
    for diag in by_source.values():
        assert diag["error"] is None
        assert diag["elapsed_ms"] >= 0
    # Diagnostics counts reconcile with the flattened item list.
    assert sum(d["count"] for d in by_source.values()) == body["count"]


def test_search_provider_error_is_captured_not_fatal(
    client: TestClient,
    fake_registry: InventoryProviderRegistry,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    # One broken upstream degrades the search (its error is attributed in
    # ``sources``) instead of failing the whole request with a 500.
    fake_registry.register(FakeBrokenProvider())
    resp = client.get("/search-inventory?keyword=como", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    by_source = {d["source"]: d for d in body["sources"]}
    assert by_source["broken"]["count"] == 0
    assert "RuntimeError" in by_source["broken"]["error"]
    assert "upstream exploded" in by_source["broken"]["error"]
    # Healthy providers still return their items.
    assert {item["source"] for item in body["items"]} == {"ov", "mock"}
    assert by_source["ov"]["error"] is None


def test_search_single_source_diagnostics_scope(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/search-inventory?source=ov", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [d["source"] for d in body["sources"]] == ["ov"]
    assert body["sources"][0]["count"] == body["count"]


# ── Sources listing route ──────────────────────────────────────────────────


def test_list_inventory_sources_returns_registered_names(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/inventory/sources", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"sources": ["ov", "mock"]}


def test_list_inventory_sources_requires_jwt(
    client: TestClient, override_registry: InventoryProviderRegistry
) -> None:
    resp = client.get("/inventory/sources")
    assert resp.status_code == 401


# ── Detail route ───────────────────────────────────────────────────────────


def test_get_inventory_detail_returns_item(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/inventory/ov/ov-como-1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "ov"
    assert body["source_id"] == "ov-como-1"
    assert body["kind"] == "experience"


def test_get_inventory_detail_missing_returns_404(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/inventory/ov/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "inventory_not_found"


def test_get_inventory_detail_unknown_source_returns_400(
    client: TestClient,
    override_registry: InventoryProviderRegistry,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get("/inventory/banana/whatever", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unknown_source"


# ── OpenAPI surface ────────────────────────────────────────────────────────


def test_openapi_exposes_inventory_contract(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/search-inventory" in paths
    assert "/inventory/sources" in paths
    assert "/inventory/{source}/{source_id}" in paths
