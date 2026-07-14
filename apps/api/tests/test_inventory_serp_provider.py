"""Tests for ``SerpHotelProvider`` — snapshot loader + geo/keyword search.

The provider serves a committed JSON snapshot (harvested offline by
``scripts/scrape_serp_hotels.py``) and adds local haversine geo-search over
it. These tests drive a tiny hand-built snapshot rather than the real
committed file so the assertions are stable regardless of what the last
scrape pulled.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.inventory.providers.serp import SerpHotelProvider
from app.inventory.registry import InventoryCtx

CTX = InventoryCtx(actor_kind="system")

# Litochoro (the Mt Olympus base) and two towns fanning out from it, plus one
# deliberately-far hotel in Athens to exercise radius clipping.
LITOCHORO = (40.1008, 22.5011)


def _hotel(source_id: str, title: str, lat: float, lng: float, **extra: object) -> dict:
    price = extra.pop("price", None)
    item: dict = {
        "kind": "hotel",
        "source": "serp",
        "source_id": source_id,
        "title": title,
        "location": {"lat": lat, "lng": lng, "label": title},
        **extra,
    }
    if price is not None:
        item["price"] = {"amount_min": price, "currency": "EUR"}
    return item


SNAPSHOT = [
    _hotel(
        "h-lito",
        "Litochoro Base Hotel",
        40.1008,
        22.5011,
        stars=4,
        rating=4.5,
        rating_count=800,
        price=150,
    ),
    _hotel(
        "h-plaka",
        "Plaka Beach Resort",
        40.0850,
        22.5400,
        stars=5,
        rating=4.6,
        rating_count=1200,
        price=420,
    ),
    _hotel(
        "h-riviera",
        "Olympian Riviera Suites",
        40.1667,
        22.5833,
        rating=4.9,
        rating_count=12,
        price=90,
    ),
    _hotel(
        "h-athens",
        "Athens Grand",
        37.9838,
        23.7275,
        stars=5,
        rating=4.8,
        rating_count=5000,
        price=600,
    ),
]


@pytest.fixture()
def provider(tmp_path: Path) -> SerpHotelProvider:
    path = tmp_path / "serp_hotels.json"
    path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    return SerpHotelProvider(data_path=path)


async def test_no_filters_returns_all_sorted_by_quality(provider: SerpHotelProvider) -> None:
    results = await provider.search(kinds=None, keyword=None, filters={}, ctx=CTX)
    assert len(results) == 4
    # Star-rated first (both 5★, so higher rating leads), then the 4★; the
    # un-starred 4.9 rental sinks to the bottom despite its rating.
    assert [r.source_id for r in results][:2] == ["h-athens", "h-plaka"]
    assert results[-1].source_id == "h-riviera"


async def test_geo_filters_and_sorts_by_distance(provider: SerpHotelProvider) -> None:
    # A 40 km radius around Litochoro keeps the three Pieria hotels and drops
    # Athens; results come back nearest-first.
    results = await provider.search(
        kinds=["hotel"],
        keyword=None,
        filters={"near_lat": LITOCHORO[0], "near_lng": LITOCHORO[1], "radius_m": 40_000},
        ctx=CTX,
    )
    assert [r.source_id for r in results] == ["h-lito", "h-plaka", "h-riviera"]
    assert all(r.source_id != "h-athens" for r in results)


async def test_geo_accepts_ratehawk_lat_lng_alias(provider: SerpHotelProvider) -> None:
    results = await provider.search(
        kinds=None,
        keyword=None,
        filters={"latitude": LITOCHORO[0], "longitude": LITOCHORO[1], "radius_m": 2_000},
        ctx=CTX,
    )
    # Only the hotel essentially at the pin survives a tight 2 km radius.
    assert [r.source_id for r in results] == ["h-lito"]


async def test_keyword_matches_title_and_label(provider: SerpHotelProvider) -> None:
    results = await provider.search(kinds=None, keyword="riviera", filters={}, ctx=CTX)
    assert [r.source_id for r in results] == ["h-riviera"]


async def test_kinds_excluding_hotel_returns_empty(provider: SerpHotelProvider) -> None:
    results = await provider.search(kinds=["experience"], keyword=None, filters={}, ctx=CTX)
    assert results == []


async def test_min_stars_excludes_lower_and_unrated(provider: SerpHotelProvider) -> None:
    results = await provider.search(
        kinds=["hotel"], keyword=None, filters={"min_stars": 5}, ctx=CTX
    )
    ids = {r.source_id for r in results}
    # Only the two 5★ hotels; the 4★ and the unrated (no stars) rental drop.
    assert ids == {"h-plaka", "h-athens"}


async def test_max_price_filters_by_nightly_rate(provider: SerpHotelProvider) -> None:
    results = await provider.search(
        kinds=["hotel"], keyword=None, filters={"max_price": 200}, ctx=CTX
    )
    # €150 and €90 pass; €420 and €600 drop.
    assert {r.source_id for r in results} == {"h-lito", "h-riviera"}


async def test_min_price_filters_by_nightly_rate(provider: SerpHotelProvider) -> None:
    results = await provider.search(
        kinds=["hotel"], keyword=None, filters={"min_price": 400}, ctx=CTX
    )
    assert {r.source_id for r in results} == {"h-plaka", "h-athens"}


async def test_stars_and_price_combine(provider: SerpHotelProvider) -> None:
    # "5-star under €500" → only Plaka (€420); Athens is 5★ but €600.
    results = await provider.search(
        kinds=["hotel"], keyword=None, filters={"min_stars": 5, "max_price": 500}, ctx=CTX
    )
    assert [r.source_id for r in results] == ["h-plaka"]


async def test_limit_caps_results(provider: SerpHotelProvider) -> None:
    results = await provider.search(kinds=None, keyword=None, filters={"limit": 2}, ctx=CTX)
    assert len(results) == 2


async def test_get_detail_by_source_id(provider: SerpHotelProvider) -> None:
    item = await provider.get_detail(source_id="h-plaka", ctx=CTX)
    assert item is not None
    assert item.title == "Plaka Beach Resort"
    assert await provider.get_detail(source_id="nope", ctx=CTX) is None


def test_missing_snapshot_is_empty_not_fatal(tmp_path: Path) -> None:
    provider = SerpHotelProvider(data_path=tmp_path / "does_not_exist.json")
    assert provider._items == []


def test_committed_snapshot_loads() -> None:
    """The real harvested file (if present) must stay schema-valid."""
    from app.inventory.providers.serp import DEFAULT_DATA_PATH

    if not DEFAULT_DATA_PATH.exists():
        pytest.skip("no committed serp snapshot in this checkout")
    provider = SerpHotelProvider()
    assert all(item.kind == "hotel" for item in provider._items)
