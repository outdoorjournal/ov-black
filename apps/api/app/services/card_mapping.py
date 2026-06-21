"""Map a normalized ``InventoryItem`` to the card metadata a node renders.

A node's ``metadata`` IS the card-attrs dict the frontend reads directly
(``FlightCardAttrs.model_dump()`` etc. — keys like ``iata_from`` /
``depart_at`` are top-level, not nested). The card library + seed
(``seed_data/japan_itinerary.py``) establish this contract; this module is
the inventory-sourced counterpart so a node created from a Duffel offer (or
any provider item) renders the same way a seeded card does.

Flights map to the typed :class:`FlightCardAttrs`, hotels to
:class:`HotelCardAttrs`, and Google-Places meals to :class:`MealCardAttrs`.
Remaining kinds (experience, destination, …) fall back to the legacy
``{"snapshot": …}`` shape the experience cards already consume — enough to
render a title/photo/price. A Places *experience* (attraction) deliberately
stays on that shared snapshot path: it renders identically to an OV
experience, and ``parse_card_attrs`` re-inflates the snapshot into an
:class:`ExperienceCardAttrs` on read, so no provider-specific typing is
needed there.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.inventory.providers.duffel import summarize_offer
from app.inventory.providers.google_places import summarize_place
from app.inventory.providers.ratehawk import summarize_hotel
from app.inventory.schemas import (
    FlightItem,
    HotelItem,
    InventoryItem,
    Location,
    MealItem,
)
from app.schemas.card_attrs import (
    CardSnapshot,
    FlightCardAttrs,
    GeoPoint,
    HotelCardAttrs,
    MealCardAttrs,
)


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


def _as_date(value: Any) -> date | None:
    """Coerce a datetime / date / ISO string to a ``date`` (or ``None``)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _hotel_price_label(item: HotelItem) -> str | None:
    if item.price is None:
        return None
    amount = item.price.amount_min
    currency = item.price.currency
    if amount is None or not currency:
        return None
    return f"{currency} {amount:,.0f}"


def _hotel_snapshot(item: HotelItem, summary: dict[str, Any]) -> CardSnapshot:
    """The chip-strip preview, mirroring the seed's hotel ``CardSnapshot``."""
    activities = [
        str(v)
        for v in (summary.get("room_type"), summary.get("bedding"), summary.get("board"))
        if v
    ]
    label = item.location.label if item.location and item.location.label else None
    return CardSnapshot(
        title=item.title,
        cover_image=item.photos[0] if item.photos else None,
        price=_hotel_price_label(item),
        location=label,
        activities=activities,
    )


def hotel_item_to_card_attrs(
    item: HotelItem,
    *,
    check_in: Any = None,
    check_out: Any = None,
) -> HotelCardAttrs:
    """Map a Ratehawk-sourced :class:`HotelItem` to :class:`HotelCardAttrs`.

    Reads the headline facts via :func:`summarize_hotel` (name, room_type,
    bedding, nights, board) and the geo anchor from the item's normalized
    ``location``. ``check_in`` / ``check_out`` are NOT in the ETG per-hotel
    response — they're the originating *search* dates, so the caller threads
    them in (str / datetime accepted); when both are present ``nights`` is
    recomputed from the stay length, otherwise it falls back to the rate's
    nightly-price count. ``night_bar`` mirrors the seed: lodging spans the
    night, so the renderer draws the softer night band.
    """
    s = summarize_hotel(item.raw)
    nights = s["nights"]
    in_date, out_date = _as_date(check_in), _as_date(check_out)
    if in_date is not None and out_date is not None and out_date > in_date:
        nights = (out_date - in_date).days
    return HotelCardAttrs(
        name=s["name"] or item.title,
        room_type=s["room_type"] or s["room_name"],
        bedding=s["bedding"],
        nights=nights,
        check_in=check_in,
        check_out=check_out,
        location=_geo_from_location(item.location),
        ambient_image=item.photos[0] if item.photos else None,
        description=item.description,
        night_bar=True,
        snapshot=_hotel_snapshot(item, s),
    )


def _cuisine_class(primary_type: str | None) -> str | None:
    """``sushi_restaurant`` → ``sushi``; ``coffee_shop`` → ``coffee shop``.

    Strips the ``_restaurant`` suffix (Google's long tail of cuisine types)
    to a bare cuisine word; a generic ``restaurant`` / ``food`` collapses to
    ``None`` (nothing useful to show). Other dining types (cafe, bar, …)
    humanize as-is.
    """
    if not primary_type:
        return None
    if primary_type in ("restaurant", "food"):
        return None
    base = (
        primary_type[: -len("_restaurant")]
        if primary_type.endswith("_restaurant")
        else primary_type
    )
    cleaned = base.replace("_", " ").strip()
    return cleaned or None


def _meal_snapshot(item: MealItem, summary: dict[str, Any]) -> CardSnapshot:
    """The chip-strip preview, mirroring the seed's meal ``CardSnapshot``."""
    cuisine = _cuisine_class(summary.get("primary_type"))
    label = item.location.label if item.location and item.location.label else None
    return CardSnapshot(
        title=item.title,
        cover_image=item.photos[0] if item.photos else None,
        price=summary.get("price_symbol"),
        location=label,
        activities=[cuisine] if cuisine else [],
    )


def meal_item_to_card_attrs(item: MealItem) -> MealCardAttrs:
    """Map a Google-Places-sourced :class:`MealItem` to :class:`MealCardAttrs`.

    Reads the headline facts via :func:`summarize_place` (primary type → a
    cuisine class, the coarse ``priceLevel`` → a ``$``-symbol) and the geo
    anchor from the item's normalized ``location``. Places gives no bookable
    amount, no seating time, and no reservation, so those typed fields stay
    ``None`` — they're filled conversationally once a table is actually held.
    """
    s = summarize_place(item.raw)
    return MealCardAttrs(
        cuisine_class=_cuisine_class(s.get("primary_type")),
        price=s.get("price_symbol"),
        location=_geo_from_location(item.location),
        ambient_image=item.photos[0] if item.photos else None,
        description=item.description,
        snapshot=_meal_snapshot(item, s),
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

    Flights get typed ``FlightCardAttrs``, hotels ``HotelCardAttrs``, and
    Places meals ``MealCardAttrs``; everything else (experiences, destinations)
    gets the snapshot fallback that ``parse_card_attrs`` re-inflates on read.
    """
    if isinstance(item, FlightItem):
        return flight_item_to_card_attrs(item).model_dump(mode="json", exclude_none=True)
    if isinstance(item, HotelItem):
        return hotel_item_to_card_attrs(item).model_dump(mode="json", exclude_none=True)
    if isinstance(item, MealItem):
        return meal_item_to_card_attrs(item).model_dump(mode="json", exclude_none=True)
    return _snapshot_fallback(item)
