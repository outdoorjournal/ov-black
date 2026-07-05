"""Fixture-driven tests for ``DuffelStaysProvider`` + ``normalize_duffel_stay``.

The adapter's real-world shape is pinned to ``tests/fixtures/duffel_stays.json``
(the ``POST /stays/search`` response). A single ``httpx.MockTransport`` handler
routes by method + path so the search + fetch-all-rates flows run offline.
Happy path + missing-params + no-creds + malformed + upstream-error + timeout +
redaction paths all live here — mirroring the flights + Ratehawk suites.
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
from app.inventory.providers.duffel_stays import (
    DuffelStaysProvider,
    ProviderUpstreamError,
    normalize_duffel_stay,
    summarize_stay,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import HotelItem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "duffel_stays.json"

# A valid hotel search: geo coordinates + check-in/out dates.
_SEARCH_FILTERS: dict[str, Any] = {
    "latitude": 51.5074,
    "longitude": -0.1416,
    "checkin": "2026-07-10",
    "checkout": "2026-07-12",
    "adults": 2,
}


@pytest.fixture(scope="module")
def stays_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture()
def stays_fixture_copy(stays_fixture: dict[str, Any]) -> dict[str, Any]:
    """Per-test deep copy so surgical edits don't bleed between tests."""
    return copy.deepcopy(stays_fixture)


def _build_provider(
    handler,
    *,
    api_key: str = "test-duffel-key",
    base_url: str = "https://api.duffel.com",
) -> DuffelStaysProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=15.0)
    settings = Settings(duffel_base_url=base_url, duffel_api_key=api_key)
    return DuffelStaysProvider(client=client, settings=settings)


def _search_handler(
    search_body: dict[str, Any],
    *,
    captured: dict[str, Any] | None = None,
):
    """Route the ``/stays/search`` POST to a canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/stays/search"):
            if captured is not None:
                captured["search_body"] = json.loads(request.content)
            return httpx.Response(200, json=search_body)
        return httpx.Response(404, json={"errors": [{"title": "not found"}]})

    return handler


# ── summarize_stay / normalize_duffel_stay (pure) ─────────────────────────


def test_summarize_stay_headline_facts(stays_fixture: dict[str, Any]) -> None:
    result = stays_fixture["data"]["results"][0]
    summary = summarize_stay(result)
    assert summary["result_id"] == "res_0000RitzLondon"
    assert summary["accommodation_id"] == "acc_0000TheRitzLondon"
    assert summary["name"] == "The Ritz London"
    # Star classification (1–5) and guest review score (0–10) are distinct.
    assert summary["star_rating"] == 5
    assert summary["review_score"] == pytest.approx(9.4)
    assert summary["review_count"] == 2871
    assert summary["latitude"] == pytest.approx(51.507273)
    assert summary["longitude"] == pytest.approx(-0.142425)
    assert summary["city"] == "London"
    assert summary["check_in_date"] == "2026-07-10"
    assert summary["check_out_date"] == "2026-07-12"
    assert summary["amount"] == pytest.approx(1840.0)
    assert summary["currency"] == "GBP"
    assert summary["expires_at"] == "2026-06-21T18:30:00Z"


def test_normalize_stay_happy_path(stays_fixture: dict[str, Any]) -> None:
    result = stays_fixture["data"]["results"][0]
    item = normalize_duffel_stay(result)

    assert isinstance(item, HotelItem)
    assert item.kind == "hotel"
    assert item.source == "duffel_stays"
    assert item.source_id == "res_0000RitzLondon"
    assert item.title == "The Ritz London"
    # Price is the cheapest whole-stay total in the quoted currency.
    assert item.price is not None
    assert item.price.currency == "GBP"
    assert item.price.amount_min == pytest.approx(1840.0)
    assert item.price.amount_max == pytest.approx(1840.0)
    # Anchored at the accommodation coordinates + labelled name, city.
    assert item.location is not None
    assert item.location.lat == pytest.approx(51.507273)
    assert item.location.label == "The Ritz London, London"
    # Star classification on ``stars``; guest review score on ``rating``.
    assert item.stars == 5
    assert item.rating == pytest.approx(9.4)
    assert item.rating_count == 2871
    assert item.phone == "+442074938181"
    # Tags carry the star + review-score summary.
    assert "5-star" in item.tags
    assert "9.4/10" in item.tags
    # Photos are the accommodation image URLs, hero first.
    assert item.photos and item.photos[0].endswith("/ritz-1.jpg")
    # raw preserves the full result for later rate-fetch / booking.
    assert item.raw == result


def test_normalize_stay_missing_id_raises(stays_fixture_copy: dict[str, Any]) -> None:
    result = stays_fixture_copy["data"]["results"][0]
    result.pop("id")
    with pytest.raises(ValueError):
        normalize_duffel_stay(result)


def test_normalize_stay_tolerates_sparse_shape() -> None:
    # No accommodation / geo / price should still normalize (defensive .get()).
    item = normalize_duffel_stay({"id": "res_sparse"})
    assert item.source_id == "res_sparse"
    assert item.title == "Res Sparse"  # humanized id fallback
    assert item.location is None
    assert item.price is None
    assert item.stars is None


# ── search(): happy path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_happy_path(stays_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_search_handler(stays_fixture, captured=captured))
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    # Request carried the geo location, dates, and one guest per adult.
    body = captured["search_body"]["data"]
    assert body["location"]["geographic_coordinates"] == {
        "longitude": pytest.approx(-0.1416),
        "latitude": pytest.approx(51.5074),
    }
    assert body["location"]["radius"] == 5
    assert body["check_in_date"] == "2026-07-10"
    assert body["check_out_date"] == "2026-07-12"
    assert body["guests"] == [{"type": "adult"}, {"type": "adult"}]
    assert body["rooms"] == 1
    # Both results normalized to HotelItems.
    assert len(items) == 2
    assert all(isinstance(i, HotelItem) for i in items)
    assert {i.source_id for i in items} == {"res_0000RitzLondon", "res_0000ClaridgesLondon"}


@pytest.mark.asyncio
async def test_search_forwards_children_rooms_and_radius(stays_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_search_handler(stays_fixture, captured=captured))
    filters = {**_SEARCH_FILTERS, "children": [7, 9], "rooms": 2, "radius": 12}
    try:
        await provider.search(kinds=["hotel"], keyword=None, filters=filters, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    body = captured["search_body"]["data"]
    assert body["guests"] == [
        {"type": "adult"},
        {"type": "adult"},
        {"type": "child", "age": 7},
        {"type": "child", "age": 9},
    ]
    assert body["rooms"] == 2
    assert body["location"]["radius"] == 12


@pytest.mark.asyncio
async def test_search_respects_limit(stays_fixture: dict[str, Any]) -> None:
    provider = _build_provider(_search_handler(stays_fixture))
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
async def test_search_missing_params_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without geo + dates")

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel_stays")
    try:
        # Missing checkin/checkout.
        items = await provider.search(
            kinds=["hotel"],
            keyword="london",
            filters={"latitude": 51.5, "longitude": -0.14},
            ctx=InventoryCtx(),
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "missing_search_params" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_no_credentials_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without credentials")

    provider = _build_provider(handler, api_key="")
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel_stays")
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
        return httpx.Response(500, json={"errors": [{"title": "boom"}]})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel_stays")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "upstream_status", None) == 500 for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel_stays")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "timeout" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_skips_malformed_result_keeps_rest(
    stays_fixture_copy: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Strip ``id`` from the first result — skipped while the second survives.
    stays_fixture_copy["data"]["results"][0].pop("id")
    provider = _build_provider(_search_handler(stays_fixture_copy))
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel_stays")
    try:
        items = await provider.search(
            kinds=["hotel"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == 1
    assert items[0].source_id == "res_0000ClaridgesLondon"
    assert any(rec.message == "inventory.provider.malformed" for rec in caplog.records)


# ── get_detail() ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_happy_path() -> None:
    # fetch_all_rates returns the accommodation with live rooms + rates.
    detail_body = {
        "data": {
            "id": "res_0000RitzLondon",
            "check_in_date": "2026-07-10",
            "check_out_date": "2026-07-12",
            "rooms": 1,
            "accommodation": {
                "id": "acc_0000TheRitzLondon",
                "name": "The Ritz London",
                "rating": 5,
                "review_score": 9.4,
                "location": {
                    "geographic_coordinates": {"latitude": 51.507273, "longitude": -0.142425}
                },
                "rooms": [
                    {"rates": [{"total_amount": "2100.00", "total_currency": "GBP"}]},
                    {"rates": [{"total_amount": "1840.00", "total_currency": "GBP"}]},
                ],
            },
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/stays/search_results/res_0000RitzLondon/actions/fetch_all_rates"
        )
        return httpx.Response(200, json=detail_body)

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="res_0000RitzLondon", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is not None
    assert isinstance(item, HotelItem)
    assert item.source_id == "res_0000RitzLondon"
    # Price synthesized from the cheapest of the two room rates.
    assert item.price is not None
    assert item.price.amount_min == pytest.approx(1840.0)
    assert item.price.currency == "GBP"


@pytest.mark.asyncio
async def test_get_detail_expired_result_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": [{"title": "not found"}]})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="res_expired", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": [{"title": "boom"}]})

    provider = _build_provider(handler)
    try:
        with pytest.raises(ProviderUpstreamError) as ei:
            await provider.get_detail(source_id="res_x", ctx=InventoryCtx())
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
            await provider.get_detail(source_id="res_x", ctx=InventoryCtx())
    finally:
        await provider.aclose()


# ── secret-redaction guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_never_logged(
    stays_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-duffel-key"
    provider = _build_provider(_search_handler(stays_fixture), api_key=secret)
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.duffel_stays")
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
