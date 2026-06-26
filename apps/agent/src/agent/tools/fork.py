"""Fork tool — branch the current itinerary into an alternate version (G2).

A fork is a versioned clone: a fresh itinerary carrying a deep copy of this one's
nodes/edges, editable independently of the live plan. Pre-booked nodes copy in
editable; already-booked/confirmed nodes carry over LOCKED (you can't fork away a
paid booking). Staff later diff the fork against the baseline and reconcile the
changes they accept (G3).
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def fork_itinerary(title: str | None = None) -> dict:
    """Create an alternate version (a fork) of the current itinerary.

    Use this when the traveler wants to explore a different shape for the trip
    without disturbing the agreed plan ("what if we did Kyoto instead of Osaka?",
    "show me a slower version"). The fork is a full, independent copy they can
    rework; anything already booked carries over locked, and staff reconcile the
    changes back in later.

    Args:
        title: Optional name for the fork. Defaults to ``"{baseline} (fork)"``.

    Requires an itinerary pinned to the session. Returns the fork's graph — its
    ``itinerary.id`` is the new fork, ``itinerary.forked_from_id`` points back at
    the baseline, and every node carries ``forked_from_node_id`` lineage plus a
    ``lock_reason`` on any carried-over booked node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    return await post_json(f"/itinerary/{itinerary_id}/fork", json=body)
