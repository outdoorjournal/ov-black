"""Inventory search + detail HTTP surface (M001/S02 T06).

Two routes:

- ``GET /search-inventory`` — aggregate or source-scoped search. Returns
  ``{items, count}`` where each item matches the shared ``InventoryItem``
  discriminated union regardless of provider.
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
from app.services.inventory import get_inventory_detail, search_inventory

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


class SearchInventoryResponse(BaseModel):
    items: list[InventoryItem]
    count: int


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
        default=None, ge=1, le=9, description="Adult passenger count for a flight search."
    ),
    user: AuthenticatedUser = Depends(require_user),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> SearchInventoryResponse:
    ctx = _ctx_from_user(user)
    # Server-side cap — the slice plan's 10x breakpoint note.
    effective_limit = min(limit, _MAX_LIMIT) if isinstance(limit, int) else None
    filters: dict = {}
    if effective_limit is not None:
        filters["limit"] = effective_limit
    # Flight-search params ride in ``filters``; providers that don't consume
    # them (OV, mock) ignore unknown keys. Only non-empty values are forwarded.
    for key, value in (
        ("origin", origin),
        ("destination", destination),
        ("departure_date", departure_date),
        ("return_date", return_date),
        ("cabin_class", cabin_class),
    ):
        if value:
            filters[key] = value
    if adults is not None:
        filters["adults"] = adults

    try:
        items = await search_inventory(
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

    logger.info(
        "inventory.search.request",
        extra={
            "sources": source,
            "kinds": kinds,
            "keyword": keyword,
            "count": len(items),
        },
    )
    return SearchInventoryResponse(items=items, count=len(items))


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
        item = await get_inventory_detail(
            registry, source=source, source_id=source_id, ctx=ctx
        )
    except UnknownSourceError as exc:
        logger.info(
            "inventory.detail.unknown_source",
            extra={"source": exc.source},
        )
        raise HTTPException(status_code=400, detail="unknown_source") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="inventory_not_found")
    return item
