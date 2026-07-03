"""Fixture-driven tests for ``BokunProvider`` + ``normalize_bokun_activity``.

The adapter's real-world shape is pinned to ``tests/fixtures/bokun_activities.json``
(a captured search envelope + a single-activity detail dto). A single
``httpx.MockTransport`` handler routes by method + path so the flows run offline.
Happy path + kinds-guard + no-creds + malformed + upstream-error + timeout +
signature-correctness + redaction paths all live here.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.inventory.providers.bokun import (
    BokunProvider,
    BokunUpstreamError,
    normalize_bokun_activity,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import ExperienceItem

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bokun_activities.json"

_ACCESS = "test-access-key"
_SECRET = "test-secret-key"


@pytest.fixture(scope="module")
def bokun_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture()
def search_body(bokun_fixture: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(bokun_fixture["search"])


@pytest.fixture()
def detail_body(bokun_fixture: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(bokun_fixture["detail"])


def _build_provider(
    handler,
    *,
    access_key: str = _ACCESS,
    secret_key: str = _SECRET,
    base_url: str = "https://api.bokun.io",
) -> BokunProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=15.0)
    settings = Settings(
        bokun_base_url=base_url,
        bokun_access_key=access_key,
        bokun_secret_key=secret_key,
    )
    return BokunProvider(client=client, settings=settings)


def _search_handler(body: dict[str, Any], *, captured: dict[str, Any] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["method"] = request.method
            captured["raw_path"] = request.url.raw_path.decode()
            captured["headers"] = dict(request.headers)
            if request.content:
                captured["body"] = json.loads(request.content)
        if request.method == "POST" and request.url.path == "/activity.json/search":
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"status": 404, "message": ""})

    return handler


# ── normalize_bokun_activity (pure) ───────────────────────────────────────


def test_normalize_search_item_happy_path(search_body: dict[str, Any]) -> None:
    item = normalize_bokun_activity(search_body["items"][0])

    assert isinstance(item, ExperienceItem)
    assert item.kind == "experience"
    assert item.source == "bokun"
    assert item.source_id == "1001"
    assert item.title == "Tokyo Tsukiji Sushi-Making Class"
    assert item.description == "Hand-roll nigiri with a Ginza chef after a market walk."
    # keyPhoto first, then the extra photo — de-duplicated (501 appears once).
    assert item.photos == [
        "https://cdn.bokun.io/photos/501/original.jpg",
        "https://cdn.bokun.io/photos/502/original.jpg",
    ]
    # Bare search price → default currency.
    assert item.price is not None
    assert item.price.amount_min == pytest.approx(120.0)
    assert item.price.currency == "USD"
    assert item.location is not None
    assert item.location.lat == pytest.approx(35.6655)
    assert item.location.label == "Tokyo, JP"
    # Operator name + keywords become tags.
    assert item.tags[0] == "Ginza Culinary Studio"
    assert "food" in item.tags
    assert item.raw == search_body["items"][0]


def test_normalize_detail_dto_happy_path(detail_body: dict[str, Any]) -> None:
    item = normalize_bokun_activity(detail_body)

    assert item.source_id == "1001"  # int64 id coerced to str
    assert item.description.startswith("A three-hour hands-on workshop")
    # Detail carries an explicit currency via nextDefaultPriceMoney.
    assert item.price is not None
    assert item.price.currency == "JPY"
    assert item.price.amount_min == pytest.approx(120.0)
    # googlePlace geo + city/country label.
    assert item.location is not None
    assert item.location.lat == pytest.approx(35.6655)
    assert item.location.label == "Tokyo, Japan"
    # difficultyLevel → difficulty range; durationDays==0 → no duration.
    assert item.difficulty is not None
    assert item.difficulty.min == pytest.approx(1.0)
    assert item.duration_days is None


def test_normalize_missing_id_raises(search_body: dict[str, Any]) -> None:
    activity = search_body["items"][0]
    activity.pop("id")
    with pytest.raises(ValueError):
        normalize_bokun_activity(activity)


def test_normalize_tolerates_sparse_shape() -> None:
    item = normalize_bokun_activity({"id": "bare-1"})
    assert item.source_id == "bare-1"
    assert item.title == "Experience"
    assert item.location is None
    assert item.price is None
    assert item.photos == []


# ── search(): happy path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_happy_path(search_body: dict[str, Any]) -> None:
    captured: dict[str, Any] = {}
    provider = _build_provider(_search_handler(search_body, captured=captured))
    try:
        items = await provider.search(
            kinds=["experience"], keyword="sushi", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == 2
    assert all(isinstance(i, ExperienceItem) for i in items)
    assert {i.source_id for i in items} == {"1001", "1002"}
    # Query params baked into the signed path; keyword forwarded as a Bokun
    # TextFilter OBJECT (a bare string 400s upstream).
    assert captured["raw_path"] == "/activity.json/search?lang=EN&currency=USD"
    assert captured["body"] == {
        "textFilter": {
            "text": "sushi",
            "searchTitle": True,
            "searchFullText": True,
            "wildcard": True,
        }
    }
    # All three Bokun auth headers present.
    assert set(captured["headers"]) >= {
        "x-bokun-date",
        "x-bokun-accesskey",
        "x-bokun-signature",
    }
    assert captured["headers"]["x-bokun-accesskey"] == _ACCESS


@pytest.mark.asyncio
async def test_search_signature_is_correct_hmac(search_body: dict[str, Any]) -> None:
    """Recompute the signature independently and assert the header matches."""
    captured: dict[str, Any] = {}
    provider = _build_provider(_search_handler(search_body, captured=captured))
    try:
        await provider.search(kinds=None, keyword=None, filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    date = captured["headers"]["x-bokun-date"]
    path = captured["raw_path"]
    string_to_sign = f"{date}{_ACCESS}POST{path}"
    expected = base64.b64encode(
        hmac.new(_SECRET.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    assert captured["headers"]["x-bokun-signature"] == expected


# ── search(): guard paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_kinds_guard_skips_upstream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called for a non-experience search")

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=["flight"], keyword=None, filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []


@pytest.mark.asyncio
async def test_search_no_credentials_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without credentials")

    provider = _build_provider(handler, secret_key="")
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.bokun")
    try:
        items = await provider.search(kinds=None, keyword=None, filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "no_credentials" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_non_2xx_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key.", "fields": {}})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.bokun")
    try:
        items = await provider.search(kinds=None, keyword=None, filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "upstream_status", None) == 401 for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_timeout_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.bokun")
    try:
        items = await provider.search(kinds=None, keyword=None, filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert items == []
    assert any(getattr(rec, "reason", None) == "timeout" for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_skips_malformed_item_keeps_rest(
    search_body: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    search_body["items"][0].pop("id")  # first item now un-normalizable
    provider = _build_provider(_search_handler(search_body))
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.bokun")
    try:
        items = await provider.search(kinds=None, keyword=None, filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert len(items) == 1
    assert items[0].source_id == "1002"
    assert any(rec.message == "inventory.provider.malformed" for rec in caplog.records)


# ── get_detail() ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_happy_path(detail_body: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/activity.json/1001"
        assert request.url.raw_path.decode() == "/activity.json/1001?lang=EN&currency=USD"
        return httpx.Response(200, json=detail_body)

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="1001", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is not None
    assert isinstance(item, ExperienceItem)
    assert item.source_id == "1001"


@pytest.mark.asyncio
async def test_get_detail_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": 404, "message": ""})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="missing", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": 500, "message": "boom"})

    provider = _build_provider(handler)
    try:
        with pytest.raises(BokunUpstreamError) as ei:
            await provider.get_detail(source_id="1001", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_get_detail_connection_error_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot connect", request=request)

    provider = _build_provider(handler)
    try:
        with pytest.raises(BokunUpstreamError):
            await provider.get_detail(source_id="1001", ctx=InventoryCtx())
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_get_detail_no_credentials_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream must not be called without credentials")

    provider = _build_provider(handler, access_key="")
    try:
        with pytest.raises(BokunUpstreamError):
            await provider.get_detail(source_id="1001", ctx=InventoryCtx())
    finally:
        await provider.aclose()


# ── secret-redaction guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_key_never_logged(
    search_body: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-bokun-signing-key"
    provider = _build_provider(_search_handler(search_body), secret_key=secret)
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.bokun")
    try:
        await provider.search(kinds=None, keyword="tour", filters={}, ctx=InventoryCtx())
    finally:
        await provider.aclose()

    for record in caplog.records:
        assert secret not in record.getMessage()
        for value in vars(record).values():
            assert secret not in repr(value)
