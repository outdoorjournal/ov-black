"""Scraped-hotel ``InventoryProvider`` with local haversine geo-search.

Unlike the live upstreams (Duffel, Ratehawk), this provider never calls out
at request time. It serves a committed JSON snapshot
(``app/inventory/data/serp_hotels.json``) harvested offline from SerpApi's
Google Hotels engine by ``scripts/scrape_serp_hotels.py``. That makes it the
demo-safe way to search a real region's hotels: no keys, no latency, no quota
at request time, and it participates in the normal aggregate fan-out so the
agent finds these hotels alongside everything else.

The snapshot ships ``HotelItem`` dicts already in the normalized
``InventoryItem`` shape, so loading is just a Pydantic validation pass (same
contract as :class:`MockProvider`). The one thing this provider adds over the
mock is *geo*: a caller passing ``near_lat``/``near_lng`` (Google Places bias
convention) or ``latitude``/``longitude`` (Ratehawk hotel-geo convention)
gets a distance-filtered, distance-sorted result — the "hotels near Mt
Olympus" query the workbench and agent actually make.

Missing-file is tolerated (empty provider + a warning) rather than fatal:
the provider is enabled by default, so a checkout that hasn't run the scraper
yet must still boot. A *malformed* file still fails loudly — that's drift, not
absence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.inventory.registry import InventoryCtx, InventoryProvider
from app.inventory.schemas import InventoryItem
from app.services.analyze_runners.common import haversine_km

logger = logging.getLogger("ov_black.inventory.serp")


DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "serp_hotels.json"

# When a caller supplies a geo centre but no explicit radius, keep everything
# within this many metres. Generous on purpose — a regional "hotels near X"
# search wants the whole cluster of nearby towns, not just the one at the pin.
DEFAULT_RADIUS_M = 40_000.0

_ITEMS_ADAPTER: TypeAdapter[list[InventoryItem]] = TypeAdapter(list[InventoryItem])


def _load_snapshot(path: Path) -> list[InventoryItem]:
    """Parse + validate the snapshot. Empty when absent; raises when malformed."""
    if not path.exists():
        logger.warning(
            "inventory.serp.snapshot_missing",
            extra={"path": str(path)},
        )
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"serp hotel snapshot at {path} must be a JSON array of items")
    return _ITEMS_ADAPTER.validate_python(payload)


def _geo_centre(filters: dict[str, Any]) -> tuple[float, float] | None:
    """Resolve a search centre from either naming convention, or ``None``.

    Accepts ``near_lat``/``near_lng`` (Google Places bias) first, falling back
    to ``latitude``/``longitude`` (Ratehawk hotel geo). Both halves must be
    present and finite numbers (and not ``bool``, which is an ``int`` subclass).
    """
    for lat_key, lng_key in (("near_lat", "near_lng"), ("latitude", "longitude")):
        lat = filters.get(lat_key)
        lng = filters.get(lng_key)
        if (
            isinstance(lat, (int, float))
            and not isinstance(lat, bool)
            and isinstance(lng, (int, float))
            and not isinstance(lng, bool)
        ):
            return (float(lat), float(lng))
    return None


class SerpHotelProvider(InventoryProvider):
    """Serves the committed SerpApi hotel snapshot with local geo-search."""

    source = "serp"

    def __init__(self, *, data_path: Path | None = None) -> None:
        self._data_path = data_path or DEFAULT_DATA_PATH
        self._items: list[InventoryItem] = _load_snapshot(self._data_path)
        logger.info(
            "inventory.serp.loaded",
            extra={
                "source": self.source,
                "data_path": str(self._data_path),
                "item_count": len(self._items),
            },
        )

    async def search(
        self,
        *,
        kinds: list[str] | None,
        keyword: str | None,
        filters: dict[str, Any],
        ctx: InventoryCtx,
    ) -> list[InventoryItem]:
        # This provider only carries hotels; a kinds filter that excludes them
        # is an instant empty rather than a full scan.
        if kinds is not None and "hotel" not in set(kinds):
            return []

        needle = keyword.casefold() if keyword else None
        centre = _geo_centre(filters)
        radius_m = _radius_m(filters)
        min_stars = _int_filter(filters, "min_stars")
        min_price = _num_filter(filters, "min_price")
        max_price = _num_filter(filters, "max_price")

        # (distance_km | None, item) so we can sort by proximity when a centre
        # is given and fall back to rating otherwise.
        scored: list[tuple[float | None, InventoryItem]] = []
        for item in self._items:
            if needle is not None and not _keyword_matches(item, needle):
                continue
            if not _passes_class_price(item, min_stars, min_price, max_price):
                continue
            distance_km: float | None = None
            if centre is not None:
                loc = item.location
                if loc is None or loc.lat is None or loc.lng is None:
                    continue  # can't place it → excluded from a geo search
                distance_km = haversine_km(centre[0], centre[1], loc.lat, loc.lng)
                if distance_km * 1000.0 > radius_m:
                    continue
            scored.append((distance_km, item))

        if centre is not None:
            scored.sort(key=lambda pair: pair[0] if pair[0] is not None else float("inf"))
        else:
            # No geo intent — surface the properties a concierge would lead
            # with: star-rated hotels, best-reviewed first. Keeps a lone
            # 5.0-from-one-review rental from outranking a 4.6 grand hotel.
            scored.sort(
                key=lambda pair: (
                    # ``stars`` lives only on HotelItem; the snapshot is all
                    # hotels but the union type doesn't know that.
                    -(getattr(pair[1], "stars", 0) or 0),
                    -(pair[1].rating or 0.0),
                    -(pair[1].rating_count or 0),
                    pair[1].title,
                )
            )

        matches = [item for _, item in scored]

        limit = filters.get("limit")
        if isinstance(limit, int) and limit > 0:
            matches = matches[:limit]

        logger.info(
            "inventory.provider.search",
            extra={
                "source": self.source,
                "keyword": keyword,
                "geo": centre is not None,
                "result_count": len(matches),
            },
        )
        return matches

    async def get_detail(
        self,
        *,
        source_id: str,
        ctx: InventoryCtx,
    ) -> InventoryItem | None:
        for item in self._items:
            if item.source_id == source_id:
                return item
        return None


def _int_filter(filters: dict[str, Any], key: str) -> int | None:
    v = filters.get(key)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _num_filter(filters: dict[str, Any], key: str) -> float | None:
    v = filters.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _passes_class_price(
    item: InventoryItem,
    min_stars: int | None,
    min_price: float | None,
    max_price: float | None,
) -> bool:
    """Star-class + nightly-price gate for a hotel.

    A hotel that *can't confirm* a constraint is excluded rather than kept: an
    unrated (no ``stars``) property fails a ``min_stars`` filter, and a hotel
    with no nightly rate fails any price bound — "5-star under €300" should
    never surface something we can't vouch meets it. Prices are in the
    snapshot's scrape currency (EUR for the Olympus set). No filter set ⇒ pass.
    """
    if min_stars is not None:
        stars = getattr(item, "stars", None)
        if not isinstance(stars, int) or stars < min_stars:
            return False
    if min_price is not None or max_price is not None:
        amount = item.price.amount_min if item.price else None
        if amount is None:
            return False
        if min_price is not None and amount < min_price:
            return False
        if max_price is not None and amount > max_price:
            return False
    return True


def _radius_m(filters: dict[str, Any]) -> float:
    radius = filters.get("radius_m")
    if isinstance(radius, (int, float)) and not isinstance(radius, bool) and radius > 0:
        return float(radius)
    return DEFAULT_RADIUS_M


def _keyword_matches(item: InventoryItem, needle: str) -> bool:
    """Case-insensitive substring match over title, description, tags, label."""
    haystacks: list[str] = [item.title]
    if item.description:
        haystacks.append(item.description)
    haystacks.extend(item.tags)
    if item.location and item.location.label:
        haystacks.append(item.location.label)
    return any(needle in h.casefold() for h in haystacks)


# Re-export so a ``ValidationError`` on a drifting snapshot is catchable by
# callers/tests without reaching into pydantic.
__all__ = ["SerpHotelProvider", "ValidationError"]
