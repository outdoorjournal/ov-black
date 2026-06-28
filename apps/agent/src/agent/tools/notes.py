"""Note tool — the traveler leaves feedback on the itinerary graph.

A note is a first-class ``note`` node (0014, dual-mode): attach it to an existing
node to annotate it ("why are we doing this at 1:30?"), or drop a free-standing
note at a time to request something new ("a dinner between these activities").
The advisor reads notes in the graph and makes the real adjustments. A note lands
on whatever itinerary is pinned — the agreed plan directly, or an alternative
version the traveler is shaping. Hits the same ``POST /itinerary/{id}/nodes``
write route as ``propose_card``; the API is the single source of truth.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def add_note(
    text: str,
    node_id: str | None = None,
    starts_at: str | None = None,
) -> dict:
    """Leave a note on the itinerary for staff to act on.

    Two shapes — pick exactly one:

    - **Attached** — pass ``node_id`` to hang the note off an existing node, for
      a question or comment about that item ("why are we doing this at 1:30?").
    - **Free-standing** — omit ``node_id`` and pass ``starts_at`` (ISO-8601 with
      offset, e.g. ``"2025-07-02T19:30:00+09:00"``) to drop a note at a point in
      the timeline, for a request to add something there ("something for dinner
      between these activities"). Choose a time inside the gap the traveler means.

    A note is feedback the advisor reads and acts on — you are not changing the
    plan yourself. It lands on whatever itinerary is pinned (the agreed plan, or
    an alternative version). Requires an itinerary pinned to the session. Returns
    the persisted note node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")

    payload: dict[str, Any] = {"type": "note", "status": "proposed", "title": text}
    if node_id is not None:
        payload["attached_to_node_id"] = node_id
    elif starts_at is not None:
        payload["starts_at"] = starts_at
    else:
        raise BackendError(status=None, reason="note_needs_anchor")

    return await post_json(f"/itinerary/{itinerary_id}/nodes", json=payload)
