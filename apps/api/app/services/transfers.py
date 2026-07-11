"""Ground-transfer builder — turn a real route into a tier-aware drive card.

The routing engine (``app.services.route_plan.compute_route``, Google Routes)
already gives verifiable geometry — distance, duration, polyline. This module
wraps that into a *persisted, schedulable* ``drive`` card: the "reserve a black
car from the airport" gesture, sized to the travel party and priced by service
tier. Because the geometry is real, the card survives a live "make it a taxi
instead" change during a demo — only the trim (vehicle, labels, estimate) flexes.

Service tiers, coarse and honest:

- ``chauffeur_black`` — a chauffeured luxury car (default for a Black-tier trip).
- ``first_class`` — a premium sedan / SUV, driver included.
- ``standard_taxi`` — a metered taxi.

Vehicle capacity scales with party size (sedan → SUV → van), so a family of five
doesn't get quoted a two-seater.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.schemas.card_attrs import DriveCardAttrs, GeoPoint, Vehicle
from app.services.route_plan import RoutePlan

ServiceClass = Literal["chauffeur_black", "first_class", "standard_taxi"]

_SERVICE_LABEL: dict[str, str] = {
    "chauffeur_black": "Chauffeured black car",
    "first_class": "First-class car",
    "standard_taxi": "Taxi",
}

# Per-km estimate by tier (native currency of the destination is the caller's
# problem; we quote a round figure the advisor can overwrite). Deliberately
# coarse — this is a demo/estimate, not a live quote.
_PER_KM_ESTIMATE: dict[str, Decimal] = {
    "chauffeur_black": Decimal("4.50"),
    "first_class": Decimal("3.00"),
    "standard_taxi": Decimal("1.60"),
}

# Base fee floor by tier so a short hop still reads as premium.
_BASE_FEE: dict[str, Decimal] = {
    "chauffeur_black": Decimal("120"),
    "first_class": Decimal("70"),
    "standard_taxi": Decimal("15"),
}


def _vehicle_for(service_class: str, party_size: int) -> Vehicle:
    """Pick a vehicle make + seat capacity for the tier and head-count."""
    if party_size >= 6:
        seats, van, sedan = 8, "Mercedes V-Class van", "Mercedes V-Class van"
    elif party_size >= 4:
        seats, van, sedan = 6, "Mercedes GLS SUV", "premium SUV"
    else:
        seats, van, sedan = 3, "Mercedes S-Class", "premium sedan"
    make = {
        "chauffeur_black": van if party_size >= 6 else sedan if party_size < 4 else van,
        "first_class": "premium SUV" if party_size >= 4 else "premium sedan",
        "standard_taxi": "estate taxi" if party_size >= 4 else "taxi",
    }.get(service_class, sedan)
    return Vehicle(make=make, capacity=seats)


def _price_estimate(service_class: str, distance_meters: int) -> Decimal:
    km = Decimal(distance_meters) / Decimal(1000)
    per_km = _PER_KM_ESTIMATE.get(service_class, _PER_KM_ESTIMATE["first_class"])
    base = _BASE_FEE.get(service_class, _BASE_FEE["first_class"])
    return (base + km * per_km).quantize(Decimal("1"))


def build_transfer_card(
    *,
    route: RoutePlan,
    service_class: str,
    party_size: int,
) -> tuple[str, DriveCardAttrs, Decimal]:
    """Build ``(title, DriveCardAttrs, price_estimate)`` from a computed route.

    The card carries the real duration / distance / polyline from ``route`` plus
    the tier trim. Price is a coarse native-currency estimate the advisor can
    overwrite; returned separately so the caller sets it as the node cost.
    """
    label = _SERVICE_LABEL.get(service_class, "Car")
    eta_minutes = round(route.duration_seconds / 60) if route.duration_seconds else None
    from_pt: GeoPoint | None = None
    to_pt: GeoPoint | None = None
    if route.legs:
        first, last = route.legs[0], route.legs[-1]
        if first.start_lat is not None and first.start_lng is not None:
            from_pt = GeoPoint(lat=first.start_lat, lng=first.start_lng, label=route.origin)
        if last.end_lat is not None and last.end_lng is not None:
            to_pt = GeoPoint(lat=last.end_lat, lng=last.end_lng, label=route.destination)

    attrs = DriveCardAttrs(
        eta_minutes=eta_minutes,
        vehicle=_vehicle_for(service_class, party_size),
        from_location=from_pt,
        to_location=to_pt,
        route_polyline=route.encoded_polyline or None,
        distance_meters=route.distance_meters or None,
        service_class=service_class,
        party_size=party_size,
    )
    title = f"{label} — {route.origin} → {route.destination}"
    price = _price_estimate(service_class, route.distance_meters)
    return title, attrs, price


__all__ = ["ServiceClass", "build_transfer_card"]
