"""Reading suggestions — the concierge's editorial voice, basecamp-only.

Before a trip has taken shape, the basecamp conversation is about dreaming and
orientation. This tool lets the agent reach into the concierge's owned media
properties (Outside, Backpacker, Climbing, Trail Runner, …) and *suggest a
read* tuned to what the traveler is drawn to — a way to keep them warm between
the dripped, deliberately un-instant planning updates.

It doesn't mutate the graph. Like the presentation surfaces, it returns a
``{surface_id, kind, payload}`` dict that :mod:`agent.translate` shapes into a
``surface`` frame; the browser slides out an article flyout (hero image, title,
publication) whose one action — "Add to reading list" — saves the piece into
the traveler's Collection as an ``article`` node. The save is a browser action,
not another tool call, so the traveler chooses what lands in their wish list.

Scope: unpinned, traveler-audience sessions only (basecamp). Once a session is
pinned to an itinerary the conversation is about *building*, not browsing — the
tool declines there so it can't clutter planning turns.
"""

from __future__ import annotations

import uuid

from strands import tool

from agent.backend import BackendError, agent_get_json, pin_ctx


def _surface_id() -> str:
    return f"srf-{uuid.uuid4().hex[:12]}"


@tool
async def suggest_reading(query: str) -> dict:
    """Suggest one editorial article for the traveler to read, as a flyout.

    Use this in the basecamp conversation when a read would land well — the
    traveler is dreaming about a place, circling an interest, or waiting on a
    planning update and you want to hand them something worth their time from
    the concierge's own magazines. Not a substitute for planning: it browses,
    it doesn't build.

    Args:
        query: What to look for, in plain words — a destination, an activity,
            or both ("trail running in the Dolomites", "Patagonia", "onsen
            wellness"). Build it from what the traveler has told you they're
            drawn to; the catalog is searched by relevance.

    Returns ``{"surface_id", "kind": "article", "payload": {...}}`` — the
    payload carries ``title``, ``publication``, ``url`` and (when present)
    ``og_image``, ``excerpt`` and ``reading_time_minutes`` for the flyout.
    Introduce it in one warm line of prose; the flyout carries the rest and
    the traveler taps "Add to reading list" to save it. Returns
    ``{"error": "<reason>"}`` instead when there's nothing to offer
    (``no_reading_found``) or the session isn't a basecamp one
    (``only_in_basecamp`` / ``only_for_traveler``) — narrate that, don't retry.
    """
    pin = pin_ctx.get() or {}
    # Basecamp = unpinned + traveler. A pinned session is about building a
    # specific trip; browsing editorial there would be noise.
    if pin.get("itinerary_id") is not None:
        return {"error": "only_in_basecamp"}
    if pin.get("audience") != "traveler":
        return {"error": "only_for_traveler"}

    try:
        data = await agent_get_json(
            "/agent/reading/search", params={"q": query, "limit": 3}
        )
    except BackendError as exc:
        return {"error": exc.reason}

    results = (data or {}).get("results") if isinstance(data, dict) else None
    if not results:
        return {"error": "no_reading_found"}

    top = results[0]
    payload: dict = {
        "title": top.get("title", ""),
        "url": top.get("url", ""),
        "publication": top.get("source_property", ""),
    }
    if top.get("og_image"):
        payload["og_image"] = top["og_image"]
    if top.get("excerpt"):
        payload["excerpt"] = top["excerpt"]
    if top.get("reading_time_minutes") is not None:
        payload["reading_time_minutes"] = top["reading_time_minutes"]

    return {"surface_id": _surface_id(), "kind": "article", "payload": payload}
