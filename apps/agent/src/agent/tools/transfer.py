"""Ground-transfer tool — add a real, tier-aware transfer card.

Unlike ``present_route`` (which slides out a map drawer but writes nothing),
``add_transfer`` persists a schedulable ground-transfer card whose geometry —
distance, drive time — is computed by a live routing engine on the backend. Use
it for "reserve a car from the airport" and similar A→B legs: the numbers are
real, so the card survives a later "make it a taxi instead" change (only the
tier and vehicle flex; the route stays true).
"""

from __future__ import annotations

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def add_transfer(
    origin: str,
    destination: str,
    mode: str = "drive",
    party_size: int = 1,
    service_class: str = "chauffeur_black",
) -> dict:
    """Add a real ground transfer from A to B as a schedulable card.

    The backend computes the actual route (distance, drive time, map polyline)
    and lands a ``drive`` card in the Collection, sized to the party and priced
    by tier.

    Args:
        origin / destination: loose place strings ("Thessaloniki Airport",
            "Litochoro") — the same names you'd use in prose.
        mode: ``drive`` (default), ``walk``, ``bicycle``, or ``transit``.
        party_size: how many travelers ride — picks the vehicle capacity
            (sedan → SUV → van). Default from the trip's party.
        service_class: the tier — ``chauffeur_black`` (a chauffeured luxury car,
            the default for this clientele), ``first_class`` (a premium sedan/
            SUV), or ``standard_taxi``. Match it to what the traveler wants.

    Lands unscheduled in the Collection (schedulable — it can be placed on a day
    later). Returns the persisted node; the entrypoint yields a ``card_proposed``
    frame. Errors: ``no_pinned_itinerary``, or a backend reason like
    ``route_not_found`` (unroutable pair — try another mode or say so).
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_pinned_itinerary")
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes/from-route",
        json={
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "party_size": party_size,
            "service_class": service_class,
        },
    )
