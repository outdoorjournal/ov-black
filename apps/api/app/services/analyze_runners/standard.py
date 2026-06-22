"""Standard Analyze runner — physical-feasibility envelope (Phase 5 / B5).

Layers drive-time feasibility on top of the shallow structural checks: for each
pair of consecutive timed, located nodes it estimates travel time as
``haversine_km / per-mode speed cap + buffer`` and emits a ``location_flux``
finding when the scheduled gap can't physically absorb the trip. No live
traffic — that's the deferred ``deep`` tier (D-ANALYZE). Computed drive-times
are also surfaced in ``result.drive_times`` so Fill (B6) can skip its own
queries.

This is the tier the B5 acceptance targets: a standard analyze over an
itinerary with an impossible drive-time gap yields a ``warn`` ``location_flux``
finding with structured evidence.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FindingSeverity, NodeType
from app.services.analyze_runners import shallow
from app.services.analyze_runners.common import (
    MODE_SPEEDS,
    Finding,
    GraphNode,
    RunOutput,
    drive_mode_for_distance,
    haversine_km,
    transit_minutes,
    transit_mode_of,
)

# Below this distance two nodes are effectively co-located — skip flux emission
# to avoid flagging same-venue transitions (their drive_time is still recorded).
# The mode-speed table + intercity threshold live in `common` so Fill (B6)
# shares the exact same physical-feasibility model.
_MIN_FLUX_KM = 0.2


def _resolve_mode(cur: GraphNode, distance_km: float) -> str | None:
    """Travel mode for reaching ``cur`` from the prior node.

    A transit node names its own mode; a `flight` is governed by schedule (skip
    haversine); everything else defaults to driving, escalated to intercity
    speed past the shared intercity threshold.
    """
    if cur.type is NodeType.flight:
        return None
    mode = transit_mode_of(cur) or "drive"
    if mode == "drive":
        return drive_mode_for_distance(distance_km)
    return mode


def _flux_findings(
    nodes: list[GraphNode],
) -> tuple[list[Finding], dict[str, dict[str, Any]]]:
    """Drive-time feasibility over consecutive timed, located pairs."""
    findings: list[Finding] = []
    drive_times: dict[str, dict[str, Any]] = {}
    located = [
        n
        for n in nodes
        if n.has_point and n.starts_lower is not None and n.starts_upper is not None
    ]
    for prev, cur in zip(located, located[1:], strict=False):
        assert prev.lat is not None and prev.lng is not None
        assert cur.lat is not None and cur.lng is not None
        assert cur.starts_lower is not None and prev.starts_upper is not None
        distance_km = haversine_km(prev.lat, prev.lng, cur.lat, cur.lng)
        mode = _resolve_mode(cur, distance_km)
        if mode is None:  # flight — schedule governs, not haversine
            continue
        speed_kmh, _buffer_min = MODE_SPEEDS[mode]
        required_min = transit_minutes(distance_km, mode)
        available_min = round((cur.starts_lower - prev.starts_upper).total_seconds() / 60)
        # Report the urban/intercity split back as a plain `drive` to callers.
        report_mode = "drive" if mode == "drive_intercity" else mode
        drive_times[f"{prev.node_id}:{cur.node_id}"] = {
            "minutes": round(required_min),
            "distance_km": round(distance_km, 1),
            "mode": report_mode,
        }
        if distance_km < _MIN_FLUX_KM or required_min <= available_min:
            continue
        findings.append(
            Finding(
                # Negative gap = the next node starts before this one ends *and*
                # travel is needed: physically impossible -> block. Otherwise a
                # too-tight-but-positive window is a warn.
                severity=(FindingSeverity.block if available_min < 0 else FindingSeverity.warn),
                category="location_flux",
                message=(
                    f"Getting from “{prev.title or 'Untitled'}” to "
                    f"“{cur.title or 'Untitled'}” needs ~{round(required_min)} min "
                    f"by {report_mode} but only {available_min} min are scheduled."
                ),
                node_id=cur.node_id,
                evidence={
                    "from_node_id": str(prev.node_id),
                    "to_node_id": str(cur.node_id),
                    "distance_km": round(distance_km, 1),
                    "available_min": available_min,
                    "required_min": round(required_min),
                    "mode": report_mode,
                    "max_speed_kmh": speed_kmh,
                },
            )
        )
    return findings, drive_times


async def run(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    scope: dict[str, Any] | None = None,
) -> RunOutput:
    findings, nodes, fuzz = await shallow.collect(session, itinerary_id=itinerary_id, scope=scope)
    flux, drive_times = _flux_findings(nodes)
    return RunOutput(
        findings=findings + flux,
        node_count=len(nodes),
        fuzz_count=fuzz,
        result_extra={"drive_times": drive_times},
    )


__all__ = ["run"]
