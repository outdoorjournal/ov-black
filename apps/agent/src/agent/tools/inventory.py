"""Inventory read tools — search across providers, fetch detail."""

from __future__ import annotations

from strands import tool

from agent.backend import get_json


@tool
async def search_inventory(
    keyword: str | None = None,
    kinds: list[str] | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> dict:
    """Search Outdoor Voyage inventory for candidate experiences.

    Args:
        keyword: Free text (destination, activity, mood). Matched by the
            OV adapter's keyword index. Optional — omit to browse.
        kinds: Filter by ``InventoryItem.kind`` (e.g. ``trip``, ``hotel``).
            Repeatable.
        source: Scope to one provider (``ov``, ``mock``). Omit to
            fan out across every enabled provider.
        limit: Maximum items to return. Capped at 50 server-side.

    Returns a dict with ``items`` (list) and ``count`` (int). Each item
    carries a stable ``source`` + ``source_id`` pair — pass them to
    ``propose_card`` or ``get_inventory_detail``. Never invent a
    source_id; use only values returned here.
    """
    params: dict = {}
    if keyword:
        params["keyword"] = keyword
    if kinds:
        params["kinds"] = kinds
    if source:
        params["source"] = source
    if limit is not None:
        params["limit"] = limit
    return await get_json("/search-inventory", params=params)


@tool
async def get_inventory_detail(source: str, source_id: str) -> dict:
    """Fetch full detail on one inventory item by (source, source_id).

    Returns the normalized ``InventoryItem`` shape — cover image, price,
    duration, difficulty, location, activities, and provider-specific
    metadata. Use before proposing a card if you need information the
    search result did not carry.
    """
    return await get_json(f"/inventory/{source}/{source_id}")
