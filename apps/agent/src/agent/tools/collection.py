"""Collection (wish list) tools — accumulate maybes before the timeline.

Before a trip has a scheduled timeline, the traveler and concierge pile up
things they're interested in: places to eat, places to stay, things to do,
ways to fly in, and stray notes. In the graph these are simply *unscheduled*
nodes (no ``starts_at``); scheduling one later just gives it a time. These
tools fill that pile and read it back:

- ``save_to_collection`` — save any inventory item (restaurant / hotel /
  activity / flight) by its ``(source, source_id)``.
- ``save_link_to_collection`` — save a web link the traveler pasted; the
  backend fetches its OpenGraph preview into a card.
- ``add_collection_note`` — jot a timeless note into the wish list.
- ``get_collection`` — read what's already saved, so you can shop the wish
  list before proposing something brand new.

Each write returns the persisted node; the entrypoint yields a
``card_proposed`` frame so the Collection updates live. Like ``propose_card``,
the write tools auto-create + pin a draft itinerary when the session has none.
"""

from __future__ import annotations

from typing import Any, Literal

from strands import tool

from agent.backend import BackendError, get_json, pin_ctx, post_json

# The Collection categories a pasted link can be filed under (a 1:1 subset of
# NodeType). ``article`` is the reading-list card (non-schedulable — a saved
# read). Anything else is better handled by search_inventory + save.
CollectionKind = Literal["experience", "meal", "hotel", "flight", "note", "article"]


async def _ensure_itinerary() -> str:
    """Return the pinned itinerary id, auto-creating + pinning one if absent.

    Mirrors ``propose_card`` / ``propose_flight``: a traveler can start a
    Collection before any itinerary exists, and the first save spins one up so
    the next turn runs in planning mode.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if itinerary_id:
        return str(itinerary_id)
    created = await post_json("/itinerary", json={"title": "Concierge draft"})
    itinerary_id = created.get("id")
    if not itinerary_id:
        raise BackendError(status=None, reason="itinerary_create_failed")
    pin_ctx.set({**pin, "itinerary_id": itinerary_id})
    return str(itinerary_id)


@tool
async def save_to_collection(source: str, source_id: str) -> dict:
    """Save an inventory item to the trip's Collection (wish list), unscheduled.

    This is the way to bank *anything* the traveler is interested in but isn't
    ready to place on a day yet — a restaurant, a hotel, an activity, a flight.
    The ``source``/``source_id`` pair must come from a prior
    ``search_inventory`` result — never invent them. The backend re-fetches the
    item and derives its card (a Duffel flight becomes a ``flight`` card with
    cabin/times, a Ratehawk stay a ``hotel`` card, a Places restaurant a
    ``meal`` card) — you don't hand-shape it.

    The item lands in the Collection with no time. To put it on the timeline
    later, use ``move_node`` to give it a start time. Auto-creates + pins a
    draft itinerary if the session has none. Returns the persisted node; the
    entrypoint yields a ``card_proposed`` frame so the Collection updates.
    """
    itinerary_id = await _ensure_itinerary()
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes/from-inventory",
        json={"source": source, "source_id": source_id},
    )


@tool
async def save_link_to_collection(
    url: str,
    kind: CollectionKind = "note",
    note: str | None = None,
) -> dict:
    """Save a web link the traveler pasted into the Collection as a card.

    Use this when the traveler shares a URL — a restaurant's site, a hotel, a
    blog about a hike. The backend fetches the page's OpenGraph preview (title /
    image / description) so it renders as a real card, not a bare link.

    Args:
        url: The link to save (http/https).
        kind: Which Collection lane to file it under — ``meal`` for a
            restaurant, ``hotel`` for a stay, ``experience`` for a thing to do,
            ``flight`` for a way in, ``article`` for a read / reading-list link
            (a magazine or blog piece — non-schedulable), or ``note`` (default)
            when it doesn't fit one cleanly. Pick the best fit.
        note: An optional short note to keep alongside the link.

    Lands unscheduled in the Collection. Auto-creates + pins a draft itinerary
    if the session has none. Returns the persisted node; the entrypoint yields a
    ``card_proposed`` frame so the Collection updates.
    """
    itinerary_id = await _ensure_itinerary()
    payload: dict[str, Any] = {"url": url, "kind": kind}
    if note is not None:
        payload["note"] = note
    return await post_json(f"/itinerary/{itinerary_id}/nodes/from-link", json=payload)


@tool
async def add_collection_note(text: str) -> dict:
    """Drop a free-text note into the Collection (no time, no host node).

    Use this for a stray idea or preference worth keeping visible in the wish
    list — "wants a sushi counter, not a table", "open to a day trip if the
    weather holds". Unlike ``add_note`` (which pins feedback to a point on the
    timeline for staff), a Collection note just lives in the pile, unscheduled.

    Auto-creates + pins a draft itinerary if the session has none. Returns the
    persisted note node; the entrypoint yields a ``card_proposed`` frame.
    """
    itinerary_id = await _ensure_itinerary()
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes",
        json={"type": "note", "status": "pending", "title": text},
    )


@tool
async def get_collection(itinerary_id: str | None = None) -> dict:
    """Read the trip's Collection: the unscheduled, non-discarded wish-list items.

    Call this BEFORE searching fresh inventory when you're helping build the
    timeline — if the traveler already saved a restaurant or hotel you like,
    schedule that (``move_node``) instead of proposing something new.

    Args:
        itinerary_id: UUID to read. If omitted, uses the pinned itinerary.

    Returns ``{itinerary_id, items: [{id, type, status, title, source,
    source_id, metadata, ...}]}`` — every item has no ``starts_at``.
    """
    target = itinerary_id or (pin_ctx.get() or {}).get("itinerary_id")
    if not target:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return await get_json(f"/itinerary/{target}/collection")
