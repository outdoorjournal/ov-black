"""Mutation tools — update node status, reschedule a node (move)."""

from __future__ import annotations

from typing import Any, Literal

from strands import tool

from agent.backend import BackendError, get_json, patch_json, pin_ctx


@tool
async def update_node_status(
    node_id: str,
    status: Literal[
        "idea", "proposed", "approved", "booked", "confirmed", "discarded"
    ],
) -> dict:
    """Flip a node's status — approve, discard, or revert.

    Use this in planning mode when the advisor directs a change
    ("drop the modern hotel", "approve the Bernina Express") or when
    the client is resolving an ``alternative_to`` cluster.

    If the itinerary is locked by the advisor, the API returns a
    ``locked`` outcome — surface that to the user ("the advisor is
    editing right now; try again in a moment") rather than retrying.

    If the node is already approved, booked, or confirmed, the API
    refuses the change with a ``status_locked`` reason (the node also
    carries a ``lock_reason`` you can read on the graph). That's not a
    retryable error — explain it conversationally and offer to involve an
    advisor ("that hotel is already booked; I'd need an advisor to move
    it") rather than trying again.

    Returns the updated node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return await patch_json(
        f"/itinerary/{itinerary_id}/nodes/{node_id}",
        json={"status": status},
    )


@tool
async def move_node(node_id: str, starts_at: str) -> dict:
    """Reschedule a node to a new start time — the timeline equivalent of a drag.

    ``starts_at`` is an ISO-8601 datetime WITH offset (e.g.
    ``"2025-07-02T20:00:00+09:00"``); keep the node's own timezone, and the day
    is taken from the date you pass. Use this to reshape an alternative version
    the traveler is working on, or to move a still-editable card on a draft.

    On the agreed plan an already approved/booked node is locked — the API
    refuses with ``status_locked``. Don't retry: branch an alternative version
    (``fork_itinerary``) and move it there. Requires an itinerary pinned to the
    session. Returns the updated node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")

    # The PATCH replaces metadata wholesale, so read the node's current metadata
    # and merge the new start_time in — otherwise we'd wipe its snapshot / cost /
    # duration. The backend keeps a free-standing note's starts_at column in sync
    # with metadata.start_time on its side.
    graph = await get_json(f"/itinerary/{itinerary_id}")
    nodes = (graph or {}).get("nodes", [])
    current = next((n for n in nodes if str(n.get("id")) == str(node_id)), None)
    if current is None:
        raise BackendError(status=None, reason="not_found")
    metadata: dict[str, Any] = dict(current.get("metadata") or {})
    metadata["start_time"] = starts_at

    return await patch_json(
        f"/itinerary/{itinerary_id}/nodes/{node_id}",
        json={"metadata": metadata},
    )
