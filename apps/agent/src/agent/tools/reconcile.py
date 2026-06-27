"""reconcile_alternative tool — (advisor only) merge or discard an alternative (G3).

Coarse, conversational reconcile for the *advisor* agent session: fold every
feasible change into the agreed plan, or discard the alternative. Per-change
accept/discard is the Command-Center diff view's job, not chat's. The tool
self-guards to an advisor session and the API enforces ``require_advisor`` on the
reconcile route, so a traveler can never reach it.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, get_json, pin_ctx, post_json


@tool
async def reconcile_alternative(action: str = "accept_all") -> dict:
    """(Advisor only) Merge or discard the current alternative version.

    Coarse actions only — for per-change accept/discard use the Command-Center
    diff view. ``action="accept_all"`` folds every change into the agreed plan
    (the live status gate still keeps booked nodes immutable, so a booked node's
    change comes back as ``refused_booked``, not applied). ``action="abandon"``
    discards the alternative. A traveler cannot call this — they use
    ``request_reconcile`` and an advisor executes the merge.

    Args:
        action: ``"accept_all"`` (merge every change) or ``"abandon"`` (discard).

    Returns the reconcile result (per-change outcomes), or the abandoned itinerary.
    """
    pin = pin_ctx.get() or {}
    if pin.get("actor_kind") != "advisor":
        raise BackendError(status=403, reason="advisor_only")
    fork_id = pin.get("itinerary_id")
    if not fork_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")
    if action == "abandon":
        return await post_json(f"/itinerary/{fork_id}/abandon", json={})
    if action != "accept_all":
        raise BackendError(status=None, reason="unknown_action")
    diff = await get_json(f"/itinerary/{fork_id}/diff")
    changes: list[dict[str, Any]] = [
        *diff.get("added", []),
        *diff.get("removed", []),
        *diff.get("changed", []),
        *diff.get("moved", []),
    ]
    decisions = [{"change_id": c["change_id"], "accept": True} for c in changes]
    return await post_json(f"/itinerary/{fork_id}/reconcile", json={"decisions": decisions})
