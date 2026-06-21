"""Fixture-driven tests for ``DuffelProvider`` + ``normalize_duffel_offer``.

The adapter's real-world shape is pinned to ``tests/fixtures/duffel_offers.json``
(the offer-list response). The offer-request step returns a tiny inline body.
A single ``httpx.MockTransport`` handler routes by method + path so the
two-step search flow runs offline. Happy path + missing-params + no-creds +
malformed + upstream-error + timeout + redaction paths all live here.
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
from app.inventory.providers.duffel import (
    DuffelProvider,
    ProviderUpstreamError,
    normalize_duffel_offer,
    summarize_offer,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import FlightItem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "duffel_offers.json"

_OFFER_REQUEST_ID = "orq_0000TestOfferRequest"

# A valid flight search; the provider needs origin/destination/departure_date.
_SEARCH_FILTERS: dict[str, Any] = {
    "origin": "LAX",
    "destination": "HND",
    "departure_date": "2026-07-10",
    "cabin_class": "business",
}


@pytest.fixture(scope="module")
def offers_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture()
def offers_fixture_copy(offers_fixture: dict[str, Any]) -> dict[str, Any]:
    """Per-test deep copy so surgical edits don't bleed between tests."""
    return copy.deepcopy(offers_fixture)


def _build_provider(
    handler,
    *,
    api_key: str = "test-duffel-key",
    base_url: str = "https://api.duffel.com",
) -> DuffelProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=15.0)
    settings = Settings(duffel_base_url=base_url, duffel_api_key=api_key)
    return DuffelProvider(client=client, settings=settings)


def _two_step_handler(
    offers_body: dict[str, Any],
    *,
    captured: dict[str, Any] | None = None,
):
    """Route the offer-request POST and the offers GET to canned responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.setdefault("requests", []).append(
                {"method": request.method, "path": request.url.path}
            )
        if request.method == "POST" and request.url.path.endswith("/air/offer_requests"):
            if captured is not None:
                captured["offer_request_body"] = json.loads(request.content)
                captured["offer_request_params"] = dict(request.url.params)
            return httpx.Response(201, json={"data": {"id": _OFFER_REQUEST_ID}})
        if request.method == "GET" and request.url.path.endswith("/air/offers"):
            if captured is not None:
                captured["offers_params"] = dict(request.url.params)
            return httpx.Response(200, json=offers_body)
        return httpx.Response(404, json={"errors": [{"title": "not found"}]})

    return handler


# ── summarize_offer / normalize_duffel_offer (pure) ───────────────────────


def test_summarize_offer_headline_facts(offers_fixture: dict[str, Any]) -> None:
    offer = offers_fixture["data"][0]
    summary = summarize_offer(offer)
    assert summary["iata_from"] == "LAX"
    assert summary["iata_to"] == "HND"
    assert summary["flight_code"] == "NH105"
    assert summary["carrier"] == "ANA"
    assert summary["cabin"] == "business"
    assert summary["depart_at"] == "2026-07-10T11:05:00"
    assert summary["arrive_at"] == "2026-07-11T15:40:00"
    assert summary["stops"] == 0
    # The quote is time-boxed: amount + currency + expiry are first-class so
    # the pre-booking refresh / money gate can detect staleness and repricing.
    assert summary["total_amount"] == "6420.50"
    assert summary["total_currency"] == "USD"
    assert summary["expires_at"] == "2026-06-21T18:30:00Z"


def test_normalize_offer_happy_path(offers_fixture: dict[str, Any]) -> None:
    offer = offers_fixture["data"][0]
    item = normalize_duffel_offer(offer)

    assert isinstance(item, FlightItem)
    assert item.kind == "flight"
    assert item.source == "duffel"
    assert item.source_id == "off_0000ANA105"
    assert item.title == "LAX → HND · ANA"
    # Price parsed from the decimal string in major units.
    assert item.price is not None
    assert item.price.currency == "USD"
    assert item.price.amount_min == pytest.approx(6420.50)
    # Anchored at the origin airport.
    assert item.location is not None
    assert item.location.lat == pytest.approx(33.942501)
    assert item.location.label == "Los Angeles (LAX)"
    # Tags carry carrier, cabin, stop summary.
    assert "ANA" in item.tags
    assert "business" in item.tags
    assert "nonstop" in item.tags
    # Carrier logo becomes the hero photo.
    assert item.photos and item.photos[0].endswith("/NH.svg")
    # raw preserves the full offer for later card mapping.
    assert item.raw == offer


def test_normalize_offer_missing_id_raises(offers_fixture_copy: dict[str, Any]) -> None:
    offer = offers_fixture_copy["data"][0]
    offer.pop("id")
    with pytest.raises(ValueError):
        normalize_duffel_offer(offer)


def test_normalize_offer_tolerates_sparse_shape() -> None:
    # An offer with no slices/owner should still normalize (defensive .get()).
    item = normalize_duffel_offer(
        {"id": "off_sparse", "total_amount": "100.00", "total_currency": "GBP"}
    )
    assert item.source_id == "off_sparse"
    assert item.title == "Flight"
    assert item.location is None
    assert item.price is not None and item.price.currency == "GBP"


# ── search(): happy path (two-step) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_search_happy_path_two_step(offers_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_two_step_handler(offers_fixture, captured=captured))
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    # Both upstream calls happened, in order.
    methods = [(r["method"], r["path"].rsplit("/", 1)[-1]) for r in captured["requests"]]
    assert methods == [("POST", "offer_requests"), ("GET", "offers")]
    # Offer request carried the slice + passenger + cabin we built.
    body = captured["offer_request_body"]["data"]
    assert body["slices"][0] == {
        "origin": "LAX",
        "destination": "HND",
        "departure_date": "2026-07-10",
    }
    assert body["passengers"] == [{"type": "adult"}]
    assert body["cabin_class"] == "business"
    assert captured["offer_request_params"]["return_offers"] == "false"
    # Offers list was scoped to the new request and sorted by price.
    assert captured["offers_params"]["offer_request_id"] == _OFFER_REQUEST_ID
    assert captured["offers_params"]["sort"] == "total_amount"
    # Two offers normalized to FlightItems.
    assert len(items) == 2
    assert all(isinstance(i, FlightItem) for i in items)
    assert {i.source_id for i in items} == {"off_0000ANA105", "off_0000JAL061"}


@pytest.mark.asyncio
async def test_search_round_trip_adds_return_slice(offers_fixture: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_two_step_handler(offers_fixture, captured=captured))
    filters = {**_SEARCH_FILTERS, "return_date": "2026-07-20", "adults": 2}
    try:
        await provider.search(kinds=["flight"], keyword=None, filters=filters, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    slices = captured["offer_request_body"]["data"]["slices"]
    assert len(slices) == 2
    assert slices[1] == {
        "origin": "HND",
        "destination": "LAX",
        "departure_date": "2026-07-20",
    }
    assert captured["offer_request_body"]["data"]["passengers"] == [
        {"type": "adult"},
        {"type": "adult"},
    ]


# ── search(): guard paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_missing_params_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without route params")

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword="tokyo", filters={"origin": "LAX"}, ctx=InventoryCtx()
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
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "no_credentials" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_offer_request_500_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/air/offer_requests"):
            return httpx.Response(500, json={"errors": [{"title": "boom"}]})
        raise AssertionError("offers must not be listed when the request fails")

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "upstream_status", None) == 500 for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_offers_500_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/air/offer_requests"):
            return httpx.Response(201, json={"data": {"id": _OFFER_REQUEST_ID}})
        return httpx.Response(500, json={"errors": [{"title": "boom"}]})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
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
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "timeout" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_skips_malformed_offer_keeps_rest(
    offers_fixture_copy: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Strip ``id`` from the first offer — skipped while the second survives.
    offers_fixture_copy["data"][0].pop("id")
    provider = _build_provider(_two_step_handler(offers_fixture_copy))
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.duffel")
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == 1
    assert items[0].source_id == "off_0000JAL061"
    assert any(rec.message == "inventory.provider.malformed" for rec in caplog.records)


# ── get_detail() ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_happy_path(offers_fixture: dict[str, Any]) -> None:
    offer = offers_fixture["data"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/air/offers/{offer['id']}"
        return httpx.Response(200, json={"data": offer})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id=offer["id"], ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is not None
    assert isinstance(item, FlightItem)
    assert item.source_id == offer["id"]


@pytest.mark.asyncio
async def test_get_detail_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": [{"title": "not found"}]})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="off_expired", ctx=InventoryCtx())
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
            await provider.get_detail(source_id="off_x", ctx=InventoryCtx())
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
            await provider.get_detail(source_id="off_x", ctx=InventoryCtx())
    finally:
        await provider.aclose()


# ── secret-redaction guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_never_logged(
    offers_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-duffel-key"
    provider = _build_provider(_two_step_handler(offers_fixture), api_key=secret)
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.duffel")
    try:
        await provider.search(
            kinds=["flight"], keyword=None, filters=_SEARCH_FILTERS, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    for record in caplog.records:
        assert secret not in record.getMessage()
        for value in vars(record).values():
            assert secret not in repr(value)
