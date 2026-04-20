"""Fixture-driven tests for ``OVProvider`` + ``normalize_ov_entry``.

The adapter's real-world shape is pinned to the recorded live response at
``tests/fixtures/ov_search_como.json`` (captured once, committed). Every
test here feeds that JSON (or a surgically-edited copy) through
``httpx.MockTransport`` so the suite runs offline. Happy path + malformed
entry + upstream-error + timeout paths all live here.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.inventory.providers.ov import (
    OVProvider,
    ProviderUpstreamError,
    normalize_ov_entry,
)
from app.inventory.registry import InventoryCtx
from app.inventory.schemas import ExperienceItem

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "ov_search_como.json"
)


@pytest.fixture(scope="module")
def ov_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture()
def ov_fixture_copy(ov_fixture: dict[str, Any]) -> dict[str, Any]:
    """Per-test deep copy so surgical edits don't bleed between tests."""
    return copy.deepcopy(ov_fixture)


def _build_provider(
    handler,
    *,
    base_url: str = "https://www.outdoorvoyage.com",
) -> OVProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    # Inject a minimal settings stub so the provider doesn't read the
    # (autouse) Supabase-flavored settings override from conftest.
    from app.config import Settings

    settings = Settings(ov_base_url=base_url, ov_api_key="")
    return OVProvider(client=client, settings=settings)


# ── normalize_ov_entry (pure) ─────────────────────────────────────────────


def test_normalize_ov_entry_happy_path(ov_fixture: dict[str, Any]) -> None:
    entry = ov_fixture["trips"][0]
    item = normalize_ov_entry(entry)

    assert isinstance(item, ExperienceItem)
    assert item.source == "ov"
    assert item.source_id == entry["id"]
    assert item.source_id  # non-empty
    assert item.title == entry["title"]
    # First photo is the cover image, deterministic per-fixture.
    assert item.photos
    assert item.photos[0] == entry["coverImage"]["accessUrl"]
    # All image accessUrls present (no dedupe would add no extras).
    for img in entry["images"]:
        assert img["accessUrl"] in item.photos
    # Price converted from minor units (amount=11000 exp=2 → 110.0).
    assert item.price is not None
    assert item.price.currency == "USD"
    assert item.price.amount_min == pytest.approx(110.0)
    # Location label prefers place + country name.
    assert item.location is not None
    assert item.location.lat == pytest.approx(entry["location"]["lat"])
    assert item.location.label == "Milano, Italy"
    # Tags pulled from activities[].name.
    assert "Hiking" in item.tags
    # Ranges kept as numeric Range.
    assert item.duration_days is not None
    assert item.duration_days.min == 10
    # raw preserves the full entry for later re-normalization.
    assert item.raw == entry


def test_normalize_ov_entry_missing_id_raises(ov_fixture_copy: dict[str, Any]) -> None:
    entry = ov_fixture_copy["trips"][0]
    entry.pop("id")
    with pytest.raises((ValueError, Exception)):
        normalize_ov_entry(entry)


# ── search(): happy path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_happy_path_returns_experience_items(
    ov_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ov_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert captured["url"].startswith("https://www.outdoorvoyage.com/api/search")
    assert captured["params"]["keyword"] == "como"
    assert len(items) >= 1
    first = items[0]
    assert isinstance(first, ExperienceItem)
    assert first.source == "ov"
    assert first.source_id
    assert first.title
    # Stable first-photo URL (same as fixture cover image).
    assert first.photos[0] == ov_fixture["trips"][0]["coverImage"]["accessUrl"]


@pytest.mark.asyncio
async def test_search_includes_trips_and_extra_trips(
    ov_fixture: dict[str, Any],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ov_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    expected = len(ov_fixture["trips"]) + len(ov_fixture["extraTrips"])
    assert len(items) == expected


# ── search(): malformed entries ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_skips_malformed_entry_keeps_rest(
    ov_fixture_copy: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Strip ``id`` from the first trip — should be skipped while extras stay.
    ov_fixture_copy["trips"][0].pop("id")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ov_fixture_copy)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ov")
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    expected = (len(ov_fixture_copy["trips"]) - 1) + len(ov_fixture_copy["extraTrips"])
    assert len(items) == expected
    assert any(
        rec.message == "inventory.provider.malformed" for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_search_wrong_key_fixture_skips_entries(
    ov_fixture_copy: dict[str, Any],
) -> None:
    # Replace every trip's ``title`` with an invalid type → ValidationError
    # raised by normalize_ov_entry → skip.
    for entry in ov_fixture_copy["trips"]:
        entry["title"] = None  # type: ignore[assignment]
    # Leave extraTrips intact so we can prove the rest survive.

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ov_fixture_copy)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert len(items) == len(ov_fixture_copy["extraTrips"])


# ── search(): upstream errors ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_500_returns_empty_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ov")
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert items == []
    error_logs = [
        rec for rec in caplog.records if rec.message == "inventory.provider.error"
    ]
    assert len(error_logs) == 1
    assert getattr(error_logs[0], "upstream_status", None) == 500


@pytest.mark.asyncio
async def test_search_504_timeout_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    provider = _build_provider(handler)
    caplog.set_level(logging.WARNING, logger="ov_black.inventory.ov")
    try:
        items = await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
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
async def test_search_empty_keyword_passthrough(
    ov_fixture: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=ov_fixture)

    provider = _build_provider(handler)
    try:
        items = await provider.search(
            kinds=None, keyword=None, filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    assert "keyword" not in captured["params"]
    assert len(items) >= 1


# ── get_detail() ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_detail_happy_path(ov_fixture: dict[str, Any]) -> None:
    entry = ov_fixture["trips"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/adventure/{entry['id']}"
        return httpx.Response(200, json={"success": True, "data": entry})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id=entry["id"], ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is not None
    assert isinstance(item, ExperienceItem)
    assert item.source_id == entry["id"]


@pytest.mark.asyncio
async def test_get_detail_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    provider = _build_provider(handler)
    try:
        item = await provider.get_detail(source_id="missing", ctx=InventoryCtx())
    finally:
        await provider.aclose()

    assert item is None


@pytest.mark.asyncio
async def test_get_detail_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

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


# ── secret-redaction guard ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_never_logged(
    ov_fixture: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.config import Settings

    secret = "super-secret-ov-key"
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=ov_fixture))
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = Settings(
        ov_base_url="https://www.outdoorvoyage.com",
        ov_api_key=secret,
    )
    provider = OVProvider(client=client, settings=settings)
    caplog.set_level(logging.DEBUG, logger="ov_black.inventory.ov")
    try:
        await provider.search(
            kinds=None, keyword="como", filters={}, ctx=InventoryCtx()
        )
    finally:
        await provider.aclose()

    for record in caplog.records:
        assert secret not in record.getMessage()
        for value in vars(record).values():
            assert secret not in repr(value)
