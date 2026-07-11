"""Campaign tools — build the length-snapped spine on a campaign trip.

A campaign trip (started from an inbound landing, e.g. Mount Olympus) ships
curated spine templates at a few fixed lengths. ``assemble_campaign_spine`` asks
the backend to snap the traveler's chosen dates to the nearest shipped length
and drop that skeleton onto the pinned itinerary. The snapping + instantiation
are deterministic server-side; the tool returns the ``reason`` string so you can
narrate the nudge to the traveler in your own words.
"""

from __future__ import annotations

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def assemble_campaign_spine() -> dict:
    """Lay down the curated campaign skeleton, sized to the trip's dates.

    Call this ONCE at the start of a campaign dashboard kickoff, before adding
    anything else. The backend reads the trip's chosen length, snaps it to the
    nearest shipped spine (e.g. 5 / 7 / 14 nights for Olympus), and instantiates
    that skeleton onto the itinerary — hotels, hikes, the summit, wired in order.

    Returns ``{itinerary_id, campaign_id, requested_nights, snapped_length,
    reason, node_count, edge_count}``. When ``reason`` is non-empty the length
    was snapped — narrate it warmly ("Olympus really wants at least five days,
    so I've laid it out over five…"). Errors: ``no_pinned_itinerary`` (no trip
    pinned) or a backend reason like ``not_a_campaign_itinerary``.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_pinned_itinerary")
    return await post_json(f"/itinerary/{itinerary_id}/campaign/kickoff", json={})
