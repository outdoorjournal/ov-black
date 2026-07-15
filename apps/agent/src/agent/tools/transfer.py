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
    starts_at: str | None = None,
) -> dict:
    """Add a real ground transfer from A to B as a schedulable card.

    The backend computes the actual route (distance, drive time, map polyline)
    and lands a ``drive`` card on the trip, sized to the party and priced by
    tier. Give it a ``starts_at`` so it lands ON the timeline — a transfer
    almost always connects two dated things, so it should ride between them, not
    sit dateless in the Collection.

    Args:
        origin / destination: loose place strings ("Thessaloniki Airport",
            "Litochoro") — the same names you'd use in prose.
        mode: ``drive`` (default), ``walk``, ``bicycle``, or ``transit``.
        party_size: how many travelers ride — picks the vehicle capacity
            (sedan → SUV → van). Default from the trip's party.
        service_class: the tier — ``chauffeur_black`` (a chauffeured luxury car,
            the default for this clientele), ``first_class`` (a premium sedan/
            SUV), or ``standard_taxi``. Match it to what the traveler wants.
        starts_at: when the car departs, an ISO-8601 datetime
            ("2026-08-12T14:30:00"). Read the plan (``get_itinerary``) and derive
            it from the legs the transfer bridges: an airport pickup departs
            around the flight's ``arrive_at``; a driver between two cards departs
            when the first one ends. The backend sizes the card's on-timeline
            span from the real drive time, so pass only the start. Omit ONLY
            when you genuinely can't place it (a date-less trip) — then it lands
            unscheduled in the Collection to schedule later.

    Returns the persisted node; the entrypoint yields a ``card_proposed`` frame.
    Errors: ``no_pinned_itinerary``, or a backend reason like ``route_not_found``
    (unroutable pair — try another mode or say so).
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_pinned_itinerary")
    body: dict = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "party_size": party_size,
        "service_class": service_class,
    }
    if starts_at is not None:
        body["starts_at"] = starts_at
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes/from-route",
        json=body,
    )
