"""Analyze tools — run a feasibility check over the plan and read its findings.

Makes the Analyze/Fill engine a *conversational* step (ADV-6 / G-ANALYZE-AGENT):
the advisor (or traveler) can ask the concierge to "check this plan for problems"
instead of driving the ``/analyses`` HTTP surface by hand.

The engine runs asynchronously: ``run_analysis`` queues a run (the API executes it
in a background task) and returns immediately with the run id + status;
``get_analysis_findings`` reads a run — defaulting to the most recent — and returns
its status, summary, and the structured findings. Use them together: kick off a run,
then read the findings once it reaches ``completed``. Both are read-only over the
graph (no node writes), gated by the same itinerary-read authorization as
``get_itinerary``.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, get_json, pin_ctx, post_json


def _require_pinned_itinerary() -> str:
    itinerary_id = (pin_ctx.get() or {}).get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return itinerary_id


@tool
async def run_analysis(depth: str = "standard", force_rerun: bool = False) -> dict:
    """Queue a feasibility analysis over the pinned itinerary.

    Use this when the advisor or traveler asks you to check the plan for
    problems — overlapping stops, impossible drive-times, missing details,
    pacing. The API scores each node against its neighbours and the party's
    constraints and records structured findings. The run is asynchronous: this
    returns as soon as it's queued; read the results with
    ``get_analysis_findings`` once the status is ``completed``.

    Args:
        depth: ``"shallow"`` (structural only), ``"standard"`` (default —
            physical-feasibility envelope with drive-times), or ``"deep"``.
            Standard is the right default for "check this plan"; ``deep`` is
            downgraded to standard in the MVP.
        force_rerun: By default an identical recent run is reused — a cache hit
            returns instantly, already ``completed``. Set true to force a fresh
            run after the graph changed.

    Requires an itinerary pinned to the session. Returns ``{analysis_id,
    status, cache_hit, in_flight}``. When ``cache_hit`` is true the run is
    already ``completed`` — call ``get_analysis_findings`` straight away;
    otherwise read it back once the status is terminal.
    """
    itinerary_id = _require_pinned_itinerary()
    body: dict[str, Any] = {"depth": depth, "force_rerun": force_rerun}
    return await post_json(f"/itinerary/{itinerary_id}/analyses", json=body)


@tool
async def get_analysis_findings(analysis_id: str | None = None) -> dict:
    """Read an Analyze run and its findings.

    Use this after ``run_analysis`` to see what the check turned up, or on its
    own to read the latest analysis without re-running it.

    Args:
        analysis_id: The run to read (as returned by ``run_analysis``). If
            omitted, reads the most recent run for the pinned itinerary.

    Requires an itinerary pinned to the session. Returns ``{analysis_id,
    status, depth, summary, findings}`` where each finding carries ``severity``
    (``info`` < ``suggest`` < ``warn`` < ``block``), ``category``, ``message``,
    ``node_id``, and an optional ``suggested_fix``. If the status is still
    ``queued`` or ``running`` the findings are not yet final — read again in a
    moment. Returns ``{status: "none", findings: []}`` when the itinerary has
    never been analysed.
    """
    itinerary_id = _require_pinned_itinerary()

    target = analysis_id
    if not target:
        recent = await get_json(
            f"/itinerary/{itinerary_id}/analyses", params={"limit": 1}
        )
        if not recent:
            return {"status": "none", "findings": []}
        target = recent[0]["id"]

    detail = await get_json(f"/itinerary/{itinerary_id}/analyses/{target}")
    return {
        "analysis_id": detail.get("id"),
        "status": detail.get("status"),
        "depth": detail.get("depth"),
        "summary": detail.get("summary"),
        "findings": detail.get("findings") or [],
    }
