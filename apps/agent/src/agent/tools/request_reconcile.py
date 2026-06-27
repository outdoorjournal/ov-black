"""request_reconcile tool — ask staff to merge the current alternative (G3).

A traveler (or the agent on their behalf) cannot merge an alternative version into
the agreed plan — only an advisor can. This tool stamps a merge request on the
current fork so staff see it and can execute the reconcile.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def request_reconcile(note: str | None = None) -> dict:
    """Ask staff to review and merge this alternative version into the agreed plan.

    Use this when the traveler is happy with the alternative version and wants it
    to become the real plan. You cannot merge it yourself — this records the
    request so an advisor can check feasibility and fold the changes in.

    Args:
        note: Optional message to staff (e.g. "they prefer the slower Kyoto pacing").

    Requires the session to be pinned to an alternative version. Returns the
    itinerary with ``reconcile_requested_at`` set.
    """
    pin = pin_ctx.get() or {}
    fork_id = pin.get("itinerary_id")
    if not fork_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")
    body: dict[str, Any] = {}
    if note:
        body["note"] = note
    return await post_json(f"/itinerary/{fork_id}/request-reconcile", json=body)
