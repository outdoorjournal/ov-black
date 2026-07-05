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
    region_id: int | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    checkin: str | None = None,
    checkout: str | None = None,
    residency: str | None = None,
    currency: str | None = None,
    near_lat: float | None = None,
    near_lng: float | None = None,
    radius_m: int | None = None,
) -> dict:
    """Search travel inventory for candidate experiences, hotels, flights, or places.

    Args:
        keyword: Free text (destination, activity, mood). Matched by the
            OV adapter's keyword index. Optional — omit to browse.
        kinds: Filter by ``InventoryItem.kind`` (e.g. ``experience``,
            ``hotel``, ``flight``). Repeatable.
        source: Scope to one provider (``ov``, ``mock``, ``duffel`` for
            flights, ``duffel_stays`` or ``ratehawk`` for hotels). Omit to fan
            out across every enabled provider.
        limit: Maximum items to return. Capped at 50 server-side.
        origin: Flight origin IATA code (e.g. ``LHR``). For a flight search
            pass origin + destination + departure_date together.
        destination: Flight destination IATA code (e.g. ``JFK``).
        departure_date: Flight departure date, ``YYYY-MM-DD``.
        return_date: Optional return date, ``YYYY-MM-DD`` — present ⇒ round trip.
        cabin_class: Flight cabin — ``economy`` | ``premium_economy`` |
            ``business`` | ``first``.
        adults: Adult count — flight passengers or hotel guests (default 1).
        region_id: Ratehawk region id for a hotel search. Pass with checkin +
            checkout; alternative to latitude + longitude.
        latitude: Hotel-search latitude (paired with longitude) for a geo search.
        longitude: Hotel-search longitude (paired with latitude).
        checkin: Hotel check-in date, ``YYYY-MM-DD``.
        checkout: Hotel check-out date, ``YYYY-MM-DD``.
        residency: Hotel guest residency, ISO-3166 alpha-2 lowercase (e.g. ``us``).
        currency: Hotel display currency, ISO 4217 (e.g. ``USD``).
        near_lat: Google Places location-bias latitude (paired with near_lng).
            Optional — biases meal/experience results toward this point.
        near_lng: Google Places location-bias longitude (paired with near_lat).
        radius_m: Google Places location-bias radius in metres (default 5km).

    For flights, set ``source='duffel'`` (or ``kinds=['flight']``) and supply
    the route + date params; ``keyword`` does not drive flight search. For
    hotels, set ``kinds=['hotel']`` (or pick a source: ``duffel_stays`` needs
    latitude+longitude, ``ratehawk`` takes region_id | latitude+longitude) and
    supply checkin + checkout; ``keyword`` does not drive hotel search. For
    restaurants / things to do, set
    ``kinds=['meal']`` and/or ``kinds=['experience']`` (Google Places) with a
    descriptive ``keyword`` (which drives the search, e.g. "omakase sushi in
    Roppongi"); optionally pass near_lat + near_lng to bias by location.

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
    if region_id is not None:
        params["region_id"] = region_id
    if latitude is not None:
        params["latitude"] = latitude
    if longitude is not None:
        params["longitude"] = longitude
    if checkin:
        params["checkin"] = checkin
    if checkout:
        params["checkout"] = checkout
    if residency:
        params["residency"] = residency
    if currency:
        params["currency"] = currency
    if near_lat is not None:
        params["near_lat"] = near_lat
    if near_lng is not None:
        params["near_lng"] = near_lng
    if radius_m is not None:
        params["radius_m"] = radius_m
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
