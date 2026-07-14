"""Inventory search + detail HTTP surface (M001/S02 T06).

Three routes:

- ``GET /search-inventory`` — aggregate or source-scoped search. Returns
  ``{items, count, sources}`` where each item matches the shared
  ``InventoryItem`` discriminated union regardless of provider and
  ``sources`` carries per-provider diagnostics (count, latency, captured
  error) so the workbench can attribute a misbehaving upstream.
- ``GET /inventory/sources`` — the registered provider names, so UI
  filter pills track the registry instead of hardcoding it.
- ``GET /inventory/{source}/{source_id}`` — detail lookup on a single
  provider; 404 when missing, 400 when the source isn't registered.

Both sit behind the shared JWT middleware — no PUBLIC_PATHS entry.
``actor_kind='user'`` / ``actor_id=user.sub`` are threaded through so the
eventual persistence path (S04 agent-identity work) has a stable seam.

The registry is pulled via :func:`get_inventory_registry` (a thin FastAPI
dependency) so tests can swap in a seeded fake without monkey-patching
``app.inventory.registry`` globals.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import AuthenticatedUser, require_user
from app.inventory.registry import (
    InventoryCtx,
    InventoryProviderRegistry,
    UnknownSourceError,
    get_registry,
)
from app.inventory.schemas import InventoryItem
from app.services.inventory import get_inventory_detail, search_inventory_detailed

logger = logging.getLogger("ov_black.routers.inventory")

# Soft cap on per-request fan-out. Aggregate search hits every enabled
# provider so an unbounded ``limit`` multiplies upstream load. 50 matches
# the slice plan's Load Profile breakpoint.
_MAX_LIMIT = 50

router = APIRouter(tags=["inventory"])


def get_inventory_registry() -> InventoryProviderRegistry:
    """FastAPI dependency — returns the process-wide registry singleton.

    Tests override via ``app.dependency_overrides[get_inventory_registry]``
    so a seeded fake registry can be injected without touching module
    globals.
    """
    return get_registry()


class SearchSourceDiagnostics(BaseModel):
    """Per-provider outcome of one search fan-out."""

    source: str
    count: int
    elapsed_ms: int
    error: str | None = None


class SearchInventoryResponse(BaseModel):
    items: list[InventoryItem]
    count: int
    # One entry per provider the search actually hit, in selection order.
    sources: list[SearchSourceDiagnostics] = []


class InventorySourcesResponse(BaseModel):
    sources: list[str]


def _ctx_from_user(user: AuthenticatedUser) -> InventoryCtx:
    return InventoryCtx(actor_kind="user", actor_id=user.sub)


@router.get(
    "/search-inventory",
    response_model=SearchInventoryResponse,
    summary="Search inventory across one or more providers.",
)
async def search_inventory_endpoint(
    source: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable. Omit for aggregate fan-out across every enabled "
            "provider; set to a single value (e.g. ``ov``, ``mock``) to "
            "scope to that provider."
        ),
    ),
    kinds: list[str] | None = Query(
        default=None,
        description="Repeatable ``InventoryItem.kind`` filter.",
    ),
    keyword: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    origin: str | None = Query(
        default=None,
        description=(
            "Flight origin IATA code (e.g. ``LHR``). Flight providers (Duffel) "
            "require origin + destination + departure_date together."
        ),
    ),
    destination: str | None = Query(
        default=None, description="Flight destination IATA code (e.g. ``JFK``)."
    ),
    departure_date: str | None = Query(
        default=None, description="Flight departure date, ``YYYY-MM-DD``."
    ),
    return_date: str | None = Query(
        default=None,
        description="Optional return date, ``YYYY-MM-DD`` — present ⇒ round trip.",
    ),
    cabin_class: str | None = Query(
        default=None,
        description="Flight cabin: ``economy`` | ``premium_economy`` | ``business`` | ``first``.",
    ),
    adults: int | None = Query(
        default=None,
        ge=1,
        le=9,
        description=("Adult count — flight passengers or hotel guests (Ratehawk)."),
    ),
    region_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Ratehawk region id for a hotel search. Supply with checkin + "
            "checkout; alternative to latitude + longitude."
        ),
    ),
    latitude: float | None = Query(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Hotel-search latitude (paired with longitude) for a geo search.",
    ),
    longitude: float | None = Query(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Hotel-search longitude (paired with latitude) for a geo search.",
    ),
    checkin: str | None = Query(
        default=None, description="Hotel check-in date, ``YYYY-MM-DD`` (Ratehawk)."
    ),
    checkout: str | None = Query(
        default=None, description="Hotel check-out date, ``YYYY-MM-DD`` (Ratehawk)."
    ),
    residency: str | None = Query(
        default=None,
        description="Hotel guest residency, ISO-3166 alpha-2 lowercase (e.g. ``us``).",
    ),
    currency: str | None = Query(
        default=None, description="Hotel display currency, ISO 4217 (e.g. ``USD``)."
    ),
    near_lat: float | None = Query(
        default=None,
        ge=-90.0,
        le=90.0,
        description=(
            "Geo-search latitude (paired with near_lng). Drives the serp HOTEL "
            "search (nearest-first within radius) and biases Google Places "
            "meal/experience results toward this point."
        ),
    ),
    near_lng: float | None = Query(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Geo-search longitude (paired with near_lat).",
    ),
    radius_m: int | None = Query(
        default=None,
        ge=1,
        le=50_000,
        description=(
            "Geo-search radius in metres (serp hotels default 40km; Google "
            "Places bias default 5km)."
        ),
    ),
    regions: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable adventure-region filter (OV): ``Europe`` | ``Asia`` | "
            "``Africa`` | ``North America`` | ``South America`` | ``Oceania``."
        ),
    ),
    activity_kinds: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable OV activity-kind filter: ``Air`` | ``Land`` | ``Water`` "
            "| ``Motor`` | ``Snow`` | ``Lodging``."
        ),
    ),
    activities: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable OV activity-name filter (e.g. ``Hiking``, ``Rafting``, ``Kayaking``)."
        ),
    ),
    min_price: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Minimum price. OV: adventure price, USD major units. serp: hotel "
            "nightly rate in the snapshot currency (EUR for the Olympus set)."
        ),
    ),
    max_price: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Maximum price. OV: adventure price, USD major units (upstream cap "
            "5000). serp: hotel nightly rate in the snapshot currency (EUR)."
        ),
    ),
    min_stars: int | None = Query(
        default=None,
        ge=1,
        le=5,
        description="Minimum hotel class, 1–5 stars (serp). Unrated hotels are excluded.",
    ),
    min_difficulty: int | None = Query(
        default=None,
        ge=1,
        le=10,
        description="Adventure minimum difficulty, 1–10 (OV).",
    ),
    max_difficulty: int | None = Query(
        default=None,
        ge=1,
        le=10,
        description="Adventure maximum difficulty, 1–10 (OV).",
    ),
    page: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Adventure result page (OV serves 9 per page). Omit to let the "
            "provider satisfy ``limit`` by walking pages."
        ),
    ),
    user: AuthenticatedUser = Depends(require_user),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> SearchInventoryResponse:
    ctx = _ctx_from_user(user)
    # Server-side cap — the slice plan's 10x breakpoint note.
    effective_limit = min(limit, _MAX_LIMIT) if isinstance(limit, int) else None
    filters: dict[str, Any] = {}
    if effective_limit is not None:
        filters["limit"] = effective_limit
    # Flight (Duffel) + hotel (Ratehawk) search params ride in ``filters``;
    # providers that don't consume them (OV, mock) ignore unknown keys. Only
    # non-empty values are forwarded.
    for key, value in (
        ("origin", origin),
        ("destination", destination),
        ("departure_date", departure_date),
        ("return_date", return_date),
        ("cabin_class", cabin_class),
        ("checkin", checkin),
        ("checkout", checkout),
        ("residency", residency),
        ("currency", currency),
    ):
        if value:
            filters[key] = value
    # ``adults`` is shared (flight passengers / hotel guests); the rest are
    # numeric hotel-location params forwarded only when present.
    if adults is not None:
        filters["adults"] = adults
    if region_id is not None:
        filters["region_id"] = region_id
    if latitude is not None:
        filters["latitude"] = latitude
    if longitude is not None:
        filters["longitude"] = longitude
    # Google Places location bias (distinct from the Ratehawk hotel-geo
    # latitude/longitude above — an optional "search near here" hint).
    if near_lat is not None:
        filters["near_lat"] = near_lat
    if near_lng is not None:
        filters["near_lng"] = near_lng
    if radius_m is not None:
        filters["radius_m"] = radius_m
    # OV adventure filters — repeatable taxonomy lists + numeric ranges.
    if regions:
        filters["regions"] = regions
    if activity_kinds:
        filters["activity_kinds"] = activity_kinds
    if activities:
        filters["activities"] = activities
    if min_price is not None:
        filters["min_price"] = min_price
    if max_price is not None:
        filters["max_price"] = max_price
    if min_stars is not None:
        filters["min_stars"] = min_stars
    if min_difficulty is not None:
        filters["min_difficulty"] = min_difficulty
    if max_difficulty is not None:
        filters["max_difficulty"] = max_difficulty
    if page is not None:
        filters["page"] = page

    try:
        items, outcomes = await search_inventory_detailed(
            registry,
            sources=source,
            kinds=kinds,
            keyword=keyword,
            filters=filters,
            ctx=ctx,
        )
    except UnknownSourceError as exc:
        # Log-without-secrets: we log the requested source name, which is
        # already in the URL query string — not sensitive.
        logger.info(
            "inventory.search.unknown_source",
            extra={"source": exc.source},
        )
        raise HTTPException(status_code=400, detail="unknown_source") from exc

    diagnostics = [
        SearchSourceDiagnostics(
            source=outcome.source,
            count=len(outcome.items),
            elapsed_ms=outcome.elapsed_ms,
            error=outcome.error,
        )
        for outcome in outcomes
    ]
    logger.info(
        "inventory.search.request",
        extra={
            "sources": source,
            "kinds": kinds,
            "keyword": keyword,
            "count": len(items),
            "provider_errors": [d.source for d in diagnostics if d.error],
        },
    )
    return SearchInventoryResponse(items=items, count=len(items), sources=diagnostics)


@router.get(
    "/inventory/sources",
    response_model=InventorySourcesResponse,
    summary="List the registered inventory providers.",
)
async def list_inventory_sources_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> InventorySourcesResponse:
    return InventorySourcesResponse(sources=registry.enabled_sources())


@router.get(
    "/inventory/{source}/{source_id}",
    response_model=InventoryItem,
    summary="Fetch a single inventory item by source + source_id.",
)
async def get_inventory_detail_endpoint(
    source: str,
    source_id: str,
    user: AuthenticatedUser = Depends(require_user),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> InventoryItem:
    ctx = _ctx_from_user(user)
    try:
        item = await get_inventory_detail(registry, source=source, source_id=source_id, ctx=ctx)
    except UnknownSourceError as exc:
        logger.info(
            "inventory.detail.unknown_source",
            extra={"source": exc.source},
        )
        raise HTTPException(status_code=400, detail="unknown_source") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="inventory_not_found")
    return item
