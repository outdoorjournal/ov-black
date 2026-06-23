"""Fill tool — rank physically-feasible candidates for a gap in the plan.

Read-only over the graph: it asks the API to score inventory for an empty
window, anchored on the latest Analyze run. To actually place a result, the
agent follows up with ``propose_card`` / ``propose_flight`` using the
``inventory_source`` + ``inventory_id`` each proposal carries.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def fill_gap(
    gap_start: str,
    gap_end: str,
    desired_kinds: list[str] | None = None,
    party_id: str | None = None,
    min_score: float | None = None,
    max_proposals: int | None = None,
) -> dict:
    """Suggest feasible things to slot into an empty window in the itinerary.

    Use this when the traveler has a gap (an afternoon free, a long layover,
    an unplanned evening) and you want real, reachable options rather than
    inventing one. The API checks each candidate against the drive time from
    the surrounding stops, the party's constraints, and the latest analysis,
    and returns them ranked.

    Args:
        gap_start: Gap start, ISO 8601 with offset (e.g.
            ``2026-09-12T13:00:00+09:00``).
        gap_end: Gap end, ISO 8601 with offset.
        desired_kinds: Optional node kinds to consider (e.g. ``["meal"]`` or
            ``["meal", "experience"]``). Defaults to meals + experiences.
        party_id: Optional party to scope feasibility + constraints to.
        min_score: Optional cutoff in [0, 1] (default 0.5). Lower it to see
            tighter or less-certain options.
        max_proposals: Optional cap on how many to return (default 8).

    Requires an itinerary pinned to the session. Returns a dict with
    ``proposals`` (each carrying ``inventory_source``/``inventory_id``,
    ``score``, ``fits_in_gap``, ``rationale``, …), ``analysis_id``, and
    ``analysis_age_seconds``. Pass a proposal's source pair to ``propose_card``
    / ``propose_flight`` to place it; never invent a source_id.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")

    body: dict[str, Any] = {"gap": {"start": gap_start, "end": gap_end}}
    if desired_kinds:
        body["desired_kinds"] = desired_kinds
    if party_id:
        body["party_id"] = party_id
    if min_score is not None:
        body["min_score"] = min_score
    if max_proposals is not None:
        body["max_proposals"] = max_proposals

    return await post_json(f"/itinerary/{itinerary_id}/fill", json=body)
