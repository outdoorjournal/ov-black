"""Map a normalized ``InventoryItem`` to the card metadata a node renders.

A node's ``metadata`` IS the card-attrs dict the frontend reads directly
(``FlightCardAttrs.model_dump()`` etc. — keys like ``iata_from`` /
``depart_at`` are top-level, not nested). The card library + seed
(``seed_data/japan_itinerary.py``) establish this contract; this module is
the inventory-sourced counterpart so a node created from a Duffel offer (or
any provider item) renders the same way a seeded card does.

Flights map to the typed :class:`FlightCardAttrs`. Other kinds fall back to
the legacy ``{"snapshot": …}`` shape the experience cards already consume —
enough to render a title/photo/price while their typed mappings land in
later slices (B1 Places, B3 Ratehawk hotels).
"""

from __future__ import annotations

from typing import Any

from app.inventory.providers.duffel import summarize_offer
from app.inventory.schemas import FlightItem, InventoryItem, Location
from app.schemas.card_attrs import FlightCardAttrs, GeoPoint


def _geo(lat: Any, lng: Any, label: str | None) -> GeoPoint | None:
    """Build a GeoPoint only when both coordinates are present.

    ``GeoPoint`` requires lat+lng (card-attrs invariant), while inventory
    ``Location`` carries them optionally — so a label-only location yields
    None rather than a validation error.
    """
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return None
    return GeoPoint(lat=float(lat), lng=float(lng), label=label)


def _geo_from_location(loc: Location | None) -> GeoPoint | None:
    if loc is None:
        return None
    return _geo(loc.lat, loc.lng, loc.label)


def _dest_geo_from_offer(raw: dict[str, Any]) -> GeoPoint | None:
    """Pull the arrival airport GeoPoint from a raw Duffel offer.

    ``summarize_offer`` carries iata/cabin/times but not coordinates; the
    destination coords live on the last slice's ``destination`` place.
    """
    slices = raw.get("slices")
    if not isinstance(slices, list) or not slices:
        return None
    last = slices[-1]
    dest = last.get("destination") if isinstance(last, dict) else None
    if not isinstance(dest, dict):
        return None
    city = dest.get("city_name")
    code = dest.get("iata_code")
    label: str | None = None
    if isinstance(city, str) and city:
        label = f"{city} ({code})" if isinstance(code, str) and code else city
    elif isinstance(code, str) and code:
        label = code
    return _geo(dest.get("latitude"), dest.get("longitude"), label)


def flight_item_to_card_attrs(item: FlightItem) -> FlightCardAttrs:
    """Map a Duffel-sourced :class:`FlightItem` to :class:`FlightCardAttrs`.

    Reads the headline facts via :func:`summarize_offer` (iata, flight_code,
    cabin, depart/arrive) and the airport geometry from the item's normalized
    origin ``location`` + the offer's destination. ``depart_at`` / ``arrive_at``
    are Duffel-local ISO strings; Pydantic coerces them to ``datetime``.
    """
    s = summarize_offer(item.raw)
    from_geo = _geo_from_location(item.location)
    to_geo = _dest_geo_from_offer(item.raw)
    return FlightCardAttrs(
        iata_from=s["iata_from"],
        iata_to=s["iata_to"],
        flight_code=s["flight_code"],
        cabin=s["cabin"],
        from_location=from_geo,
        to_location=to_geo,
        # A flight's map anchor is its arrival (where the next node happens),
        # mirroring the seed's "Arrive Haneda" card (location = HND).
        location=to_geo or from_geo,
        depart_at=s["depart_at"],
        arrive_at=s["arrive_at"],
        description=item.description,
    )


def _snapshot_fallback(item: InventoryItem) -> dict[str, Any]:
    """Legacy ``snapshot`` shape for kinds without a typed mapping yet.

    Mirrors what the agent's ``propose_card`` stored for experiences, so the
    existing snapshot-reading cards (experience/hotel/destination) render.
    """
    snapshot: dict[str, Any] = {"title": item.title}
    if item.photos:
        snapshot["cover_image"] = item.photos[0]
    if item.price is not None:
        amount = item.price.amount_min
        currency = item.price.currency
        if amount is not None and currency:
            snapshot["price"] = f"{currency} {amount:,.0f}"
    if item.location is not None and item.location.label:
        snapshot["location"] = item.location.label
    return {"snapshot": snapshot}


def inventory_item_to_card_metadata(item: InventoryItem) -> dict[str, Any]:
    """Node ``metadata`` for an inventory-sourced node, keyed off ``kind``.

    Flights get typed ``FlightCardAttrs``; everything else gets the snapshot
    fallback until its typed mapping lands.
    """
    if isinstance(item, FlightItem):
        return flight_item_to_card_attrs(item).model_dump(
            mode="json", exclude_none=True
        )
    return _snapshot_fallback(item)
