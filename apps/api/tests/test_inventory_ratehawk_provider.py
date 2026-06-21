"""Fixture-driven tests for ``RatehawkProvider`` + ``normalize_ratehawk_hotel``.

The adapter's real-world shape is pinned to ``tests/fixtures/ratehawk_hotels.json``
(a ``/search/serp/region/`` response). A single ``httpx.MockTransport`` handler
routes by method + path so the search + detail flows run offline. Happy path +
geo-search + guests + missing-params + no-creds + envelope-error + malformed +
upstream-error + timeout + redaction paths all live here.

See the provider module docstring on *fixture honesty*: the ETG SERP response
proper carries only ``id``/``hid``/``rates``; the committed fixture inlines the
static content (``static_vm``) that a live integration joins from the hotel
content dump, so the full name→geo→price mapping is exercised offline.
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
from app.inventory.providers.ratehawk import (
    ProviderUpstreamError,
    RatehawkProvider,
    normalize_ratehawk_hotel,
    summarize_hotel,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import HotelItem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ratehawk_hotels.json"

# A valid region search; the provider needs (region_id | lat+lng) + dates.
_SEARCH_FILTERS: dict[str, Any] = {
    "region_id": 2381,
    "checkin": "2026-09-12",
    "checkout": "2026-09-14",
    "adults": 2,
}


@pytest.fixture(scope="module")
def hotels_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture()
def hotels_fixture_copy(hotels_fixture: dict[str, Any]) -> dict[str, Any]:
    """Per-test deep copy so surgical edits don't bleed between tests."""
    return copy.deepcopy(hotels_fixture)


def _build_provider(
    handler,
    *,
    key_id: str = "test-key-id",
    api_key: str = "test-ratehawk-key",
    base_url: str = "https://api.worldota.net/api/b2b/v3",
) -> RatehawkProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=15.0)
    settings = Settings(
        ratehawk_base_url=base_url,
        ratehawk_key_id=key_id,
        ratehawk_api_key=api_key,
    )
    return RatehawkProvider(client=client, settings=settings)


def _serp_handler(
    serp_body: dict[str, Any],
    *,
    captured: dict[str, Any] | None = None,
):
    """Route a SERP POST (region or geo) to a canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and "/search/serp/" in request.url.path:
            if captured is not None:
                captured["path"] = request.url.path
                captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=serp_body)
        return httpx.Response(404, json={"status": "error", "error": "not_found", "data": None})

    return handler


# ── summarize_hotel / normalize_ratehawk_hotel (pure) ─────────────────────


def test_summarize_hotel_headline_facts(hotels_fixture: dict[str, Any]) -> None:
    hotel = hotels_fixture["data"]["hotels"][0]
    summary = summarize_hotel(hotel)
    assert summary["hotel_id"] == "grand_hotel_tremezzo"
    assert summary["hid"] == 7654321
    assert summary["name"] == "Grand Hotel Tremezzo"
    assert summary["star_rating"] == 5
    assert summary["latitude"] == pytest.approx(45.98765)
    assert summary["longitude"] == pytest.approx(9.22891)
    assert summary["address"].startswith("Via Regina 8")
    # Headline = the *cheapest* rate (Prestige @ 3190), not the pricier suite.
    assert summary["room_name"] == "Lake View Prestige Room"
    assert summary["room_type"] == "Prestige Room"
    assert summary["bedding"] == "king bed"
    assert summary["nights"] == 2
    assert summary["board"] == "breakfast"
    assert summary["amount"] == pytest.approx(3190.0)
    assert summary["currency"] == "USD"
    assert summary["free_cancellation_before"] == "2026-09-08T12:00:00"
    assert summary["book_hash"] == "h-3f9c1d20-aaaa-tremezzo-prestige"


def test_normalize_hotel_happy_path(hotels_fixture: dict[str, Any]) -> None:
    hotel = hotels_fixture["data"]["hotels"][0]
    item = normalize_ratehawk_hotel(hotel)

    assert isinstance(item, HotelItem)
    assert item.kind == "hotel"
    assert item.source == "ratehawk"
    assert item.source_id == "grand_hotel_tremezzo"
    assert item.title == "Grand Hotel Tremezzo"
    assert item.stars == 5
    # Price taken from the cheapest rate's display amount/currency.
    assert item.price is not None
    assert item.price.currency == "USD"
    assert item.price.amount_min == pytest.approx(3190.0)
    # Located from static lat/lng + a region-qualified label.
    assert item.location is not None
    assert item.location.lat == pytest.approx(45.98765)
    assert item.location.label == "Grand Hotel Tremezzo, Lake Como"
    # Templated image URL resolved to a concrete size.
    assert item.photos and item.photos[0].endswith("/grand_tremezzo/1.jpg")
    assert "{size}" not in item.photos[0]
    assert "x500" in item.photos[0]
    # Tags carry star, board, room type, cancellation posture.
    assert "5-star" in item.tags
    assert "breakfast" in item.tags
    assert "Prestige Room" in item.tags
    assert "free cancellation" in item.tags
    # Address becomes the description.
    assert item.description is not None and item.description.startswith("Via Regina 8")
    # raw preserves the full hotel (all rates) for later rate selection.
    assert item.raw == hotel


def test_normalize_picks_cheapest_rate(hotels_fixture: dict[str, Any]) -> None:
    # Hotel 0 has a 3190 Prestige room and a 4070 suite — headline = cheaper.
    item = normalize_ratehawk_hotel(hotels_fixture["data"]["hotels"][0])
    assert item.price is not None
    assert item.price.amount_min == pytest.approx(3190.0)


def test_normalize_hotel_missing_id_raises(hotels_fixture_copy: dict[str, Any]) -> None:
    hotel = hotels_fixture_copy["data"]["hotels"][0]
    hotel.pop("id")
    with pytest.raises(ValueError):
        normalize_ratehawk_hotel(hotel)


def test_normalize_hotel_tolerates_static_less_shape() -> None:
    # A SERP hotel with no static_vm / no rates should still normalize: the
    # title falls back to a humanized id; geo + price degrade to None.
    item = normalize_ratehawk_hotel({"id": "casa_del_lago", "hid": 1})
    assert item.source_id == "casa_del_lago"
    assert item.title == "Casa Del Lago"
    assert item.location is None
    assert item.price is None
    assert item.stars is None
    assert item.photos == []


# ── search(): happy path (region) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_region_happy_path(hotels_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_serp_handler(hotels_fixture, captured=captured))
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    # Region endpoint chosen; body carried the region_id + dates + guests.
    assert captured["path"].endswith("/search/serp/region/")
    body = captured["body"]
    assert body["region_id"] == 2381
    assert body["checkin"] == "2026-09-12"
    assert body["checkout"] == "2026-09-14"
    assert body["guests"] == [{"adults": 2, "children": []}]
    assert body["currency"] == "USD"
    assert body["residency"] == "us"
    # Two hotels normalized to HotelItems.
    assert len(items) == 2
    assert all(isinstance(i, HotelItem) for i in items)
    assert {i.source_id for i in items} == {
        "grand_hotel_tremezzo",
        "il_sereno_lago_di_como",
    }


@pytest.mark.asyncio
async def test_search_geo_uses_geo_endpoint(hotels_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_serp_handler(hotels_fixture, captured=captured))
    filters = {
        "latitude": 45.98,
        "longitude": 9.25,
        "radius": 4000,
        "checkin": "2026-09-12",
        "checkout": "2026-09-14",
        "adults": 2,
        "children": [7],
    }
    try:
        await provider.search(
            kinds=["hotel"], keyword=None, filters=filters, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert captured["path"].endswith("/search/serp/geo/")
    body = captured["body"]
    assert body["latitude"] == pytest.approx(45.98)
    assert body["longitude"] == pytest.approx(9.25)
    assert body["radius"] == 4000
    assert "region_id" not in body
    # Children ages thread into the guest block.
    assert body["guests"] == [{"adults": 2, "children": [7]}]


@pytest.mark.asyncio
async def test_search_limit_caps_results(hotels_fixture: dict[str, Any]) -> None:
    provider = _build_provider(_serp_handler(hotels_fixture))
    try:
        items = await provider.search(
            kinds=["hotel"],
            keyword=None,
            filters={**_SEARCH_FILTERS, "limit": 1},
            ctx=InventoryCtx(),
        )
    finally:
        await provider.aclose()

    assert len(items) == 1


# ── search(): guard paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_missing_dates_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without dates")

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters={"region_id": 2381}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(
        getattr(rec, "reason", None) == "missing_search_params" for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_search_missing_region_and_geo_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without a location")

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"],
            keyword=None,
            filters={"checkin": "2026-09-12", "checkout": "2026-09-14"},
            ctx=InventoryCtx(),
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(
        getattr(rec, "reason", None) == "missing_search_params" for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_search_no_credentials_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without credentials")

    provider = _build_provider(handler, key_id="", api_key="")
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "no_credentials" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_partial_credentials_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A key_id without an api_key (or vice versa) is not usable credentials.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called with partial creds")

    provider = _build_provider(handler, api_key="")
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "no_credentials" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_500_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error", "error": "boom"})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "upstream_status", None) == 500 for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_envelope_error_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    # ETG returns HTTP 200 with status='error' for business failures.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "error", "error": "unknown_region", "data": None}
        )

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(
        getattr(rec, "reason", None) in {"envelope_status", "envelope_error"}
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "timeout" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_skips_malformed_hotel_keeps_rest(
    hotels_fixture_copy: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Strip ``id`` from the first hotel — skipped while the second survives.
    hotels_fixture_copy["data"]["hotels"][0].pop("id")
    provider = _build_provider(_serp_handler(hotels_fixture_copy))
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ratehawk")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == 1
    assert items[0].source_id == "il_sereno_lago_di_como"
    assert any(rec.message == "inventory.provider.malformed" for rec in caplog.records)


# ── get_detail() ──────────────────────────────────────────────────────────


def _info_response(hotel_id: str, static: dict[str, Any]) -> dict[str, Any]:
    """An ``/hotel/info/`` envelope wrapping static content (no rates)."""
    return {"status": "ok", "error": None, "data": {"id": hotel_id, **static}}


@pytest.mark.asyncio
async def test_get_detail_happy_path(hotels_fixture: dict[str, Any]) -> None:
    static = hotels_fixture["data"]["hotels"][0]["static_vm"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/hotel/info/")
        assert json.loads(request.content)["id"] == "grand_hotel_tremezzo"
        return httpx.Response(200, json=_info_response("grand_hotel_tremezzo", static))

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(
            source_id="grand_hotel_tremezzo", ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert item is not None
    assert isinstance(item, HotelItem)
    assert item.source_id == "grand_hotel_tremezzo"
    assert item.title == "Grand Hotel Tremezzo"
    assert item.stars == 5
    assert item.location is not None and item.location.lat == pytest.approx(45.98765)
    # Static content has no rates, so detail carries no price.
    assert item.price is None


@pytest.mark.asyncio
async def test_get_detail_unknown_hotel_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "error", "error": "hotel_not_found", "data": None}
        )

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="nope", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error", "error": "boom"})

    provider = _build_provider(handler)
    try:
        with pytest.raises(ProviderUpstreamError) as ei:
            await provider.get_detail(source_id="x", ctx=InventoryCtx())
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
            await provider.get_detail(source_id="x", ctx=InventoryCtx())
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_get_detail_no_credentials_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without credentials")

    provider = _build_provider(handler, key_id="", api_key="")
    try:
        with pytest.raises(ProviderUpstreamError):
            await provider.get_detail(source_id="x", ctx=InventoryCtx())
    finally:
        await provider.aclose()


# ── secret-redaction guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_never_logged(
    hotels_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-ratehawk-key"
    provider = _build_provider(_serp_handler(hotels_fixture), api_key=secret)
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.ratehawk")
    try:
        await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    for record in caplog.records:
        assert secret not in record.getMessage()
        for value in vars(record).values():
            assert secret not in repr(value)
