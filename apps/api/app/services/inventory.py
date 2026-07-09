"""Service facade over the inventory provider registry (M001/S02 T06).

Thin wrapper so routers don't import the registry directly — keeps the
dispatch-vs-aggregate logic in one place and gives tests a single seam to
override. ``search_inventory`` picks between registry.search_all (aggregate
across every enabled source) and a single-provider ``search`` based on the
``sources`` argument; ``get_inventory_detail`` is a direct dispatch.

Unknown sources bubble up as ``UnknownSourceError`` so the router can map
them to a deterministic HTTP 400.
"""

from __future__ import annotations

from typing import Any

from app.inventory.registry import (
    InventoryCtx,
    InventoryProviderRegistry,
    ProviderSearchOutcome,
    UnknownSourceError,
)
from app.inventory.schemas import InventoryItem

__all__ = [
    "InventoryCtx",
    "UnknownSourceError",
    "search_inventory",
    "search_inventory_detailed",
    "get_inventory_detail",
]


async def search_inventory(
    registry: InventoryProviderRegistry,
    *,
    sources: list[str] | None,
    kinds: list[str] | None,
    keyword: str | None,
    filters: dict[str, Any],
    ctx: InventoryCtx,
) -> list[InventoryItem]:
    """Search inventory across one or more sources.

    ``sources=None`` (or empty) → aggregate fan-out across every enabled
    provider. A single-element list targets that one provider directly so
    tests (and the mock-scoped slice demo) get byte-identical output to
    the aggregate path for that source.
    """
    if sources and len(sources) == 1:
        provider = registry.get(sources[0])
        return await provider.search(kinds=kinds, keyword=keyword, filters=filters, ctx=ctx)
    normalized_sources = sources if sources else None
    return await registry.search_all(
        sources=normalized_sources,
        kinds=kinds,
        keyword=keyword,
        filters=filters,
        ctx=ctx,
    )


async def search_inventory_detailed(
    registry: InventoryProviderRegistry,
    *,
    sources: list[str] | None,
    kinds: list[str] | None,
    keyword: str | None,
    filters: dict[str, Any],
    ctx: InventoryCtx,
) -> tuple[list[InventoryItem], list[ProviderSearchOutcome]]:
    """Like ``search_inventory`` but with per-provider diagnostics.

    Provider errors are captured on their outcome instead of propagating, so
    one misbehaving upstream degrades the search rather than failing it.
    Item ordering matches ``search_inventory``: a single requested source
    keeps that provider's own order; aggregate fan-out is stably sorted by
    (source, source_id).
    """
    normalized_sources = sources if sources else None
    outcomes = await registry.search_all_detailed(
        sources=normalized_sources,
        kinds=kinds,
        keyword=keyword,
        filters=filters,
        ctx=ctx,
    )
    items = [item for outcome in outcomes for item in outcome.items]
    if normalized_sources is None or len(normalized_sources) > 1:
        items.sort(key=lambda item: (item.source, item.source_id))
    return items, outcomes


async def get_inventory_detail(
    registry: InventoryProviderRegistry,
    *,
    source: str,
    source_id: str,
    ctx: InventoryCtx,
) -> InventoryItem | None:
    provider = registry.get(source)
    return await provider.get_detail(source_id=source_id, ctx=ctx)
