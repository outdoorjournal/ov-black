"""Fixture-driven tests for ``GooglePlacesProvider`` + its pure helpers.

The adapter's real-world shape is pinned to recorded Places API (New)
responses at ``tests/fixtures/google_places_searchtext.json`` (Text Search)
and ``tests/fixtures/google_places_details.json`` (Place Details). Every test
feeds that JSON (or a surgically-edited copy) through ``httpx.MockTransport``
so the suite runs offline. Pure-function classification + normalization,
two-shape search params, every degrade path, and key redaction all live here.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.inventory.providers.google_places import (
    GooglePlacesProvider,
    ProviderUpstreamError,
    classify_kind,
    normalize_place,
    summarize_place,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import ExperienceItem, MealItem

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SEARCH_FIXTURE = FIXTURE_DIR / "google_places_searchtext.json"
DETAIL_FIXTURE = FIXTURE_DIR / "google_places_details.json"

_BASE_URL = "https://places.googleapis.com"


@pytest.fixture(scope="module")
def search_fixture() -> dict[str, Any]:
    return json.loads(SEARCH_FIXTURE.read_text())


@pytest.fixture()
def search_fixture_copy(search_fixture: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(search_fixture)


@pytest.fixture(scope="module")
def detail_fixture() -> dict[str, Any]:
    return json.loads(DETAIL_FIXTURE.read_text())


def _build_provider(handler, *, api_key: str = "test-places-key") -> GooglePlacesProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = Settings(
        google_places_base_url=_BASE_URL,
        google_places_api_key=api_key,
    )
    return GooglePlacesProvider(client=client, settings=settings)


def _places(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return fixture["places"]


# ── classify_kind (pure) ───────────────────────────────────────────────────


def test_classify_restaurant_is_meal(search_fixture: dict[str, Any]) -> None:
    sushi = _places(search_fixture)[0]
    assert classify_kind(sushi) == "meal"


def test_classify_attraction_is_experience(search_fixture: dict[str, Any]) -> None:
    shrine = _places(search_fixture)[1]
    assert classify_kind(shrine) == "experience"


def test_classify_lodging_is_experience(search_fixture: dict[str, Any]) -> None:
    aman = _places(search_fixture)[2]
    assert classify_kind(aman) == "experience"


def test_classify_cuisine_suffix_is_meal() -> None:
    # A long-tail cuisine type we don't enumerate still classifies as a meal
    # via the ``*_restaurant`` suffix rule.
    place = {"primaryType": "ramen_restaurant", "types": ["ramen_restaurant"]}
    assert classify_kind(place) == "meal"


# ── normalize_place (pure) ─────────────────────────────────────────────────


def test_normalize_meal_happy_path(search_fixture: dict[str, Any]) -> None:
    sushi = _places(search_fixture)[0]
    item = normalize_place(sushi)

    assert isinstance(item, MealItem)
    assert item.kind == "meal"
    assert item.source == "google_places"
    assert item.source_id == sushi["id"]
    assert item.title == "Sushi Saito"
    # Description prefers the editorial summary.
    assert item.description == sushi["editorialSummary"]["text"]
    # Location carries geo + the formatted address as its label.
    assert item.location is not None
    assert item.location.lat == pytest.approx(35.6647321)
    assert item.location.lng == pytest.approx(139.7339211)
    assert item.location.label == sushi["formattedAddress"]
    # Places never gives a bookable amount.
    assert item.price is None
    # Tags: humanized primary type + price-level symbol.
    assert "sushi restaurant" in item.tags
    assert "$$$$" in item.tags
    # Photos deliberately empty (needs a keyed proxy); refs preserved in raw.
    assert item.photos == []
    assert item.raw == sushi


def test_normalize_experience_happy_path(search_fixture: dict[str, Any]) -> None:
    shrine = _places(search_fixture)[1]
    item = normalize_place(shrine)

    assert isinstance(item, ExperienceItem)
    assert item.kind == "experience"
    assert item.title == "Fushimi Inari Taisha"
    assert item.duration_days is None
    assert item.difficulty is None


def test_normalize_falls_back_to_address_when_no_editorial(
    search_fixture: dict[str, Any],
) -> None:
    aman = _places(search_fixture)[2]  # no editorialSummary in the fixture
    item = normalize_place(aman)
    assert item.description == aman["formattedAddress"]


def test_normalize_missing_id_raises(search_fixture_copy: dict[str, Any]) -> None:
    place = _places(search_fixture_copy)[0]
    place.pop("id")
    with pytest.raises(ValueError):
        normalize_place(place)


def test_normalize_missing_display_name_raises(
    search_fixture_copy: dict[str, Any],
) -> None:
    place = _places(search_fixture_copy)[0]
    place.pop("displayName")
    with pytest.raises(ValueError):
        normalize_place(place)


def test_summarize_place_headline_facts(search_fixture: dict[str, Any]) -> None:
    summary = summarize_place(_places(search_fixture)[0])
    assert summary["name"] == "Sushi Saito"
    assert summary["kind"] == "meal"
    assert summary["primary_type"] == "sushi_restaurant"
    assert summary["rating"] == pytest.approx(4.6)
    assert summary["user_rating_count"] == 421
    assert summary["price_level"] == "PRICE_LEVEL_VERY_EXPENSIVE"
    assert summary["price_symbol"] == "$$$$"
    assert summary["latitude"] == pytest.approx(35.6647321)


# ── search(): happy path + request shape ───────────────────────────────────


@pytest.mark.asyncio
async def test_search_happy_path_classifies_items(
    search_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["field_mask"] = request.headers.get("x-goog-fieldmask")
        captured["api_key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=None, keyword="great food in Tokyo", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert captured["url"] == f"{_BASE_URL}/v1/places:searchText"
    assert captured["body"]["textQuery"] == "great food in Tokyo"
    assert "includedType" not in captured["body"]  # mixed/unset kinds
    assert captured["field_mask"].startswith("places.")
    assert captured["api_key"] == "test-places-key"
    # 3 places in the fixture → 1 meal + 2 experiences, all kept.
    assert len(items) == 3
    kinds = sorted(item.kind for item in items)
    assert kinds == ["experience", "experience", "meal"]
    assert all(item.source == "google_places" for item in items)


@pytest.mark.asyncio
async def test_search_single_kind_sends_included_type(
    search_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=["meal"], keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert captured["body"]["includedType"] == "restaurant"
    # And classified results are filtered to the requested kind.
    assert items
    assert all(item.kind == "meal" for item in items)


@pytest.mark.asyncio
async def test_search_experience_kind_maps_to_tourist_attraction(
    search_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=["experience"], keyword="shrines", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert captured["body"]["includedType"] == "tourist_attraction"
    assert all(item.kind == "experience" for item in items)


@pytest.mark.asyncio
async def test_search_location_bias_built_from_filters(
    search_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler)
    try:
        await provider.search(
            kinds=None,
            keyword="sushi",
            filters={"near_lat": 35.66, "near_lng": 139.73, "radius_m": 1500},
            ctx=InventoryCtx(),
        )
    finally:
        await provider.aclose()

    circle = captured["body"]["locationBias"]["circle"]
    assert circle["center"] == {"latitude": 35.66, "longitude": 139.73}
    assert circle["radius"] == pytest.approx(1500.0)


@pytest.mark.asyncio
async def test_search_limit_capped_into_max_result_count(
    search_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler)
    try:
        await provider.search(
            kinds=None, keyword="sushi", filters={"limit": 99}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    # 99 requested → clamped to the 20-result Text Search ceiling.
    assert captured["body"]["maxResultCount"] == 20


# ── search(): degrade paths ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_missing_keyword_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"places": []})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.google_places")
    try:
        items = await provider.search(
            kinds=None, keyword="   ", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert called["n"] == 0  # never hit the network without a query
    assert any(
        getattr(rec, "reason", None) == "missing_search_params"
        for rec in caplog.records
        if rec.message == "inventory.provider.error"
    )


@pytest.mark.asyncio
async def test_search_no_credentials_returns_empty(
    search_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=search_fixture)

    provider = _build_provider(handler, api_key="")
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.google_places")
    try:
        items = await provider.search(
            kinds=None, keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(
        getattr(rec, "reason", None) == "no_credentials"
        for rec in caplog.records
        if rec.message == "inventory.provider.error"
    )


@pytest.mark.asyncio
async def test_search_500_returns_empty_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.google_places")
    try:
        items = await provider.search(
            kinds=None, keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    error_logs = [
        rec for rec in caplog.records if rec.message == "inventory.provider.error"
    ]
    assert any(getattr(rec, "upstream_status", None) == 500 for rec in error_logs)


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.google_places")
    try:
        items = await provider.search(
            kinds=None, keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(
        getattr(rec, "reason", None) == "timeout"
        for rec in caplog.records
        if rec.message == "inventory.provider.error"
    )


@pytest.mark.asyncio
async def test_search_skips_malformed_place_keeps_rest(
    search_fixture_copy: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Drop the first place's display name → it's skipped; the other two stay.
    _places(search_fixture_copy)[0].pop("displayName")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=search_fixture_copy)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.google_places")
    try:
        items = await provider.search(
            kinds=None, keyword="tokyo", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == 2
    assert any(rec.message == "inventory.provider.malformed" for rec in caplog.records)


# ── get_detail() ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_happy_path(detail_fixture: dict[str, Any]) -> None:
    place_id = detail_fixture["id"]
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["field_mask"] = request.headers.get("x-goog-fieldmask")
        return httpx.Response(200, json=detail_fixture)

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id=place_id, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert captured["path"] == f"/v1/places/{place_id}"
    # Detail field mask is unprefixed (single place, not a places[] list).
    assert not captured["field_mask"].startswith("places.")
    assert item is not None
    assert isinstance(item, ExperienceItem)
    assert item.source_id == place_id
    assert item.title == "Fushimi Inari Taisha"


@pytest.mark.asyncio
async def test_get_detail_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="missing", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_empty_body_returns_none() -> None:
    # A 200 with no id is treated as "not found" rather than a crash.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="weird", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    provider = _build_provider(handler)
    try:
        with pytest.raises(ProviderUpstreamError) as ei:
            await provider.get_detail(source_id="abc", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_get_detail_connection_error_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot connect", request=request)

    provider = _build_provider(handler)
    try:
        with pytest.raises(ProviderUpstreamError):
            await provider.get_detail(source_id="abc", ctx=InventoryCtx())
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_get_detail_no_credentials_raises() -> None:
    provider = _build_provider(
        lambda r: httpx.Response(200, json={}), api_key=""
    )
    try:
        with pytest.raises(ProviderUpstreamError):
            await provider.get_detail(source_id="abc", ctx=InventoryCtx())
    finally:
        await provider.aclose()


# ── secret-redaction guard ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_never_logged(
    search_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-places-key"
    provider = _build_provider(
        lambda r: httpx.Response(200, json=search_fixture), api_key=secret
    )
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.google_places")
    try:
        await provider.search(
            kinds=None, keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    for record in caplog.records:
        assert secret not in record.getMessage()
        for value in vars(record).values():
            assert secret not in repr(value)
