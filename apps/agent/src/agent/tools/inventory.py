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
    origin: str | None = None,
    destination: str | None = None,
    departure_date: str | None = None,
    return_date: str | None = None,
    cabin_class: str | None = None,
    adults: int | None = None,
) -> dict:
    """Search travel inventory for candidate experiences, hotels, or flights.

    Args:
        keyword: Free text (destination, activity, mood). Matched by the
            OV adapter's keyword index. Optional — omit to browse.
        kinds: Filter by ``InventoryItem.kind`` (e.g. ``experience``,
            ``hotel``, ``flight``). Repeatable.
        source: Scope to one provider (``ov``, ``mock``, ``duffel``). Omit
            to fan out across every enabled provider.
        limit: Maximum items to return. Capped at 50 server-side.
        origin: Flight origin IATA code (e.g. ``LHR``). For a flight search
            pass origin + destination + departure_date together.
        destination: Flight destination IATA code (e.g. ``JFK``).
        departure_date: Flight departure date, ``YYYY-MM-DD``.
        return_date: Optional return date, ``YYYY-MM-DD`` — present ⇒ round trip.
        cabin_class: Flight cabin — ``economy`` | ``premium_economy`` |
            ``business`` | ``first``.
        adults: Adult passenger count for a flight search (default 1).

    For flights, set ``source='duffel'`` (or ``kinds=['flight']``) and supply
    the route + date params; ``keyword`` does not drive flight search.

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
    if origin:
        params["origin"] = origin
    if destination:
        params["destination"] = destination
    if departure_date:
        params["departure_date"] = departure_date
    if return_date:
        params["return_date"] = return_date
    if cabin_class:
        params["cabin_class"] = cabin_class
    if adults is not None:
        params["adults"] = adults
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
