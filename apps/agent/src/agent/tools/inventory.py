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
    regions: list[str] | None = None,
    activity_kinds: list[str] | None = None,
    activities: list[str] | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_stars: int | None = None,
    min_difficulty: int | None = None,
    max_difficulty: int | None = None,
    page: int | None = None,
) -> dict:
    """Search travel inventory for candidate experiences, hotels, flights, or places.

    Args:
        keyword: Free text (destination, activity, mood). Matched by the
            OV adapter's keyword index. Optional — omit to browse.
        kinds: Filter by ``InventoryItem.kind`` (e.g. ``experience``,
            ``hotel``, ``flight``). Repeatable.
        source: Scope to one provider (``ov``, ``mock``, ``duffel`` for
            flights, ``serp`` for hotels). Omit to fan out across every enabled
            provider.
        limit: Maximum items to return. Capped at 50 server-side.
        origin: Flight origin IATA code (e.g. ``LHR``). For a flight search
            pass origin + destination + departure_date together.
        destination: Flight destination IATA code (e.g. ``JFK``).
        departure_date: Flight departure date, ``YYYY-MM-DD``.
        return_date: Optional return date, ``YYYY-MM-DD`` — present ⇒ round trip.
        cabin_class: Flight cabin — ``economy`` | ``premium_economy`` |
            ``business`` | ``first``.
        adults: Adult count — flight passengers or hotel guests (default 1).
        region_id: (Unused for hotels now — kept for API compatibility.)
        latitude: Hotel-search latitude (paired with longitude) — an alias for
            ``near_lat`` accepted by the ``serp`` hotel provider.
        longitude: Hotel-search longitude (paired with latitude).
        checkin: (Optional — the ``serp`` hotel catalog is not date-gated, so
            you do NOT need check-in/out to search hotels.)
        checkout: (Optional — see ``checkin``.)
        residency: Hotel guest residency, ISO-3166 alpha-2 lowercase (e.g. ``us``).
        currency: Hotel display currency, ISO 4217 (e.g. ``USD``).
        near_lat: Geo-search latitude (paired with near_lng). Drives the
            ``serp`` HOTEL search (nearest-first within radius) and biases
            meal/experience (Google Places) results toward this point.
        near_lng: Geo-search longitude (paired with near_lat).
        radius_m: Geo-search radius in metres (serp hotels default 40km; Google
            Places bias default 5km).
        regions: Adventure-trip continent filter (OV). One or more of
            ``Europe`` | ``Asia`` | ``Africa`` | ``North America`` |
            ``South America`` | ``Oceania``.
        activity_kinds: OV activity-kind filter. One or more of ``Air`` |
            ``Land`` | ``Water`` | ``Motor`` | ``Snow`` | ``Lodging``.
        activities: OV activity-name filter, e.g. ``Hiking``, ``Trekking``,
            ``Rafting``, ``Kayaking``, ``Surfing``, ``Safari``, ``Climbing``,
            ``Skiing & Snowsports``, ``Hot Air Ballooning``.
        min_price: Minimum price. For hotels (serp): nightly rate in EUR. For
            adventures (OV): USD major units.
        max_price: Maximum price. For hotels (serp): nightly rate in EUR (e.g.
            ``max_price=300`` for "under €300/night"). For adventures (OV): USD
            major units (cap 5000).
        min_stars: Minimum HOTEL class, 1–5 stars (serp). Unrated hotels are
            excluded, so pass it only when the traveler asks for a star tier.
        min_difficulty: Adventure minimum difficulty, 1 (easy) – 10 (extreme).
        max_difficulty: Adventure maximum difficulty, 1–10.
        page: Adventure result page (9 per page). Usually omit — set a
            ``limit`` instead and paging is handled for you; pass it only to
            fetch *more* results after exhausting an earlier search.

    For flights, set ``source='duffel'`` (or ``kinds=['flight']``) and supply
    the route + date params; ``keyword`` does not drive flight search. For
    hotels, use ``source='serp'`` (or ``kinds=['hotel']``) with
    ``near_lat`` + ``near_lng`` (optionally ``radius_m``) to find accommodations
    nearest a point — a curated catalog searched by proximity, returned
    nearest-first with star class, crowd rating, photos, and nightly price. No
    check-in/out dates are needed and ``keyword`` does not drive hotel search;
    anchor a hotel search on the coordinates of where the traveler is staying
    that night. For
    restaurants / things to do, set
    ``kinds=['meal']`` and/or ``kinds=['experience']`` (Google Places) with a
    descriptive ``keyword`` (which drives the search, e.g. "omakase sushi in
    Roppongi"); optionally pass near_lat + near_lng to bias by location. For
    multi-day guided adventures and expeditions (treks, rafting, safaris,
    ski touring), search the Outdoor Voyage catalog: ``source='ov'`` with any
    of ``regions`` / ``activity_kinds`` / ``activities`` / price / difficulty
    filters — e.g. ``regions=['Asia'], activity_kinds=['Water']`` — plus an
    optional ``keyword``; combine filters rather than relying on keyword alone.

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
    if regions:
        params["regions"] = regions
    if activity_kinds:
        params["activity_kinds"] = activity_kinds
    if activities:
        params["activities"] = activities
    if min_price is not None:
        params["min_price"] = min_price
    if max_price is not None:
        params["max_price"] = max_price
    if min_stars is not None:
        params["min_stars"] = min_stars
    if min_difficulty is not None:
        params["min_difficulty"] = min_difficulty
    if max_difficulty is not None:
        params["max_difficulty"] = max_difficulty
    if page is not None:
        params["page"] = page
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
