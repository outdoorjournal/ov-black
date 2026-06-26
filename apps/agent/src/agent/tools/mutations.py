"""Mutation tools — update node status (advisor adjustments)."""

from __future__ import annotations

from typing import Literal

from strands import tool

from agent.backend import BackendError, patch_json, pin_ctx


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
