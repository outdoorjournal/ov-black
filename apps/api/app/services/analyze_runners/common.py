"""Shared types + helpers for the Analyze runners (Phase 5 / B5).

Holds the runner output contract (:class:`Finding`, :class:`RunOutput`), the
read-only graph loader (:func:`load_timeline_nodes` / :func:`load_edges`), the
haversine helper used by the standard tier, and :func:`build_result` which
folds findings into the flat, agent-readable ``analyses.result`` aggregate.

Kept separate from :mod:`app.services.analyze` so both the service (which
persists findings) and the runners (which produce them) import one contract
without a circular import.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FindingSeverity, NodeStatus, NodeType


@dataclass(frozen=True, slots=True)
class Finding:
    """One problem produced by a runner — maps 1:1 to an analysis_findings row.

    ``node_id`` is ``None`` for whole-itinerary findings. ``suggested_fix`` is
    a Phase-6-FillProposal-shaped dict (or ``None`` when informational).
    """

    severity: FindingSeverity
    category: str
    message: str
    node_id: uuid.UUID | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_fix: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RunOutput:
    """What a runner returns. ``result`` is the partial aggregate the runner
    contributes (drive_times, degraded_from, …); :func:`build_result` merges it
    with the fold-derived stats. ``external_calls`` audits provider hops."""

    findings: list[Finding]
    node_count: int
    fuzz_count: int
    result_extra: dict[str, Any] = field(default_factory=dict)
    external_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GraphNode:
    """A linearized, feasibility-relevant node. ``lat``/``lng`` are decoded from
    the PostGIS ``location`` geography; ``None`` when the node has no point."""

    node_id: uuid.UUID
    type: NodeType
    status: NodeStatus
    title: str
    starts_lower: datetime | None
    starts_upper: datetime | None
    lat: float | None
    lng: float | None
    cost_amount: Any | None
    metadata: dict[str, Any]

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lng is not None


# Transit NodeTypes whose own type names the travel mode between the node
# before them and themselves. A `flight` is feasibility-checked by schedule,
# not haversine, so it's handled separately by the standard runner.
_TRANSIT_MODES: frozenset[str] = frozenset({"subway", "train", "drive", "walk", "boat"})


_NODES_SQL = text(
    """
    select
        n.id, n.type, n.status, n.title, n.cost_amount, n.metadata,
        lower(n.starts_at) as starts_lower,
        upper(n.starts_at) as starts_upper,
        st_y(n.location::geometry) as lat,
        st_x(n.location::geometry) as lng
    from public.nodes n
    where n.itinerary_id = :iid
      and n.role is null
      and n.attached_to_node_id is null
      and n.status <> 'discarded'
      and (not cast(:selected_only as boolean) or n.is_selected_alt)
      and (
          cast(:has_node_ids as boolean) is false
          or n.id = any(cast(:node_ids as uuid[]))
      )
      and (
          cast(:party_id as uuid) is null
          or exists (
              select 1 from public.node_parties np
              where np.node_id = n.id
                and np.party_id = cast(:party_id as uuid)
          )
          or not exists (
              select 1 from public.node_parties np where np.node_id = n.id
          )
      )
    order by lower(n.starts_at) asc nulls last, n.created_at asc
    """
)

_EDGES_SQL = text(
    """
    select e.id, e.from_node_id, e.to_node_id, e.type
    from public.edges e
    where e.itinerary_id = :iid
    order by e.created_at asc
    """
)


def _scope_branches_selected_only(scope: dict[str, Any]) -> bool:
    """``branches`` defaults to ``'selected_only'`` (handoff §3.1)."""
    return bool(scope.get("branches", "selected_only") != "all")


async def load_timeline_nodes(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    scope: dict[str, Any] | None = None,
) -> list[GraphNode]:
    """Load the ordered, feasibility-relevant nodes for an itinerary.

    Skips structural roles, attached notes, and discarded nodes. Honors the
    run ``scope``: ``branches`` (selected-only by default), an optional
    ``node_ids`` allow-list, and an optional ``party_id`` filter (a node with
    no party rows is implicitly "all parties", mirroring linearization).
    """
    scope = scope or {}
    node_ids_raw = scope.get("node_ids") or []
    node_ids = [uuid.UUID(str(n)) for n in node_ids_raw]
    party_id_raw = scope.get("party_id")
    rows = (
        (
            await session.execute(
                _NODES_SQL,
                {
                    "iid": itinerary_id,
                    "selected_only": _scope_branches_selected_only(scope),
                    "has_node_ids": bool(node_ids),
                    "node_ids": node_ids,
                    "party_id": uuid.UUID(str(party_id_raw)) if party_id_raw else None,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        GraphNode(
            node_id=r["id"],
            type=NodeType(r["type"]),
            status=NodeStatus(r["status"]),
            title=r["title"],
            starts_lower=r["starts_lower"],
            starts_upper=r["starts_upper"],
            lat=r["lat"],
            lng=r["lng"],
            cost_amount=r["cost_amount"],
            metadata=r["metadata"] or {},
        )
        for r in rows
    ]


async def load_edges(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]]:
    """Return ``(edge_id, from_node_id, to_node_id, type)`` tuples."""
    rows = (await session.execute(_EDGES_SQL, {"iid": itinerary_id})).mappings().all()
    return [(r["id"], r["from_node_id"], r["to_node_id"], r["type"]) for r in rows]


def transit_mode_of(node: GraphNode) -> str | None:
    """Travel mode named by a transit node's own type, else ``None``."""
    return node.type.value if node.type.value in _TRANSIT_MODES else None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres (no live traffic — standard tier)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── shared drive-time model (standard runner + Fill) ───────────────────
# Per-mode (km/h speed cap, buffer minutes per edge). First-cut numbers from
# the Phase 5 handoff §4.2 — no live traffic. The standard Analyze runner
# (existing-pair flux) and Fill (B6 candidate envelope) share this ONE table so
# the analyzer's feasibility verdict and Fill's "what's reachable" can never
# disagree. `drive` resolves urban→intercity by distance (see below).
MODE_SPEEDS: dict[str, tuple[float, int]] = {
    "walk": (5, 0),
    "subway": (35, 5),
    "train": (80, 10),
    "drive": (25, 15),  # urban
    "drive_intercity": (70, 15),
    "boat": (25, 10),
}
# Above this haversine distance a `drive` escalates to the intercity cap.
INTERCITY_KM = 100.0


def drive_mode_for_distance(distance_km: float) -> str:
    """`drive` (urban) below :data:`INTERCITY_KM`, `drive_intercity` above."""
    return "drive_intercity" if distance_km > INTERCITY_KM else "drive"


def transit_minutes(distance_km: float, mode: str) -> float:
    """Estimated minutes for one leg: ``distance / speed cap + per-edge buffer``."""
    speed_kmh, buffer_min = MODE_SPEEDS[mode]
    return distance_km / speed_kmh * 60 + buffer_min


def _summarize(findings: list[Finding], fuzz_count: int) -> str:
    """A one-line, agent-readable headline for ``analyses.summary``."""
    blocks = sum(1 for f in findings if f.severity is FindingSeverity.block)
    warns = sum(1 for f in findings if f.severity is FindingSeverity.warn)
    if blocks:
        head = f"{blocks} blocking issue{'s' if blocks != 1 else ''}"
    elif warns:
        head = f"{warns} warning{'s' if warns != 1 else ''}"
    else:
        head = "No feasibility problems"
    fuzz = f"; {fuzz_count} node{'s' if fuzz_count != 1 else ''} still fuzzy" if fuzz_count else ""
    return head + fuzz + "."


def build_result(
    output: RunOutput,
    *,
    depth: str,
) -> dict[str, Any]:
    """Fold a :class:`RunOutput` into the flat ``analyses.result`` aggregate
    (handoff §5.3): summary + stats + by_category, merged with ``result_extra``
    (drive_times, degraded_from, …). Kept ≤ a few kb — detailed findings live
    in ``analysis_findings``."""
    findings = output.findings
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    stats = {
        "node_count": output.node_count,
        "fuzz_count": output.fuzz_count,
        "block_count": sum(1 for f in findings if f.severity is FindingSeverity.block),
        "warn_count": sum(1 for f in findings if f.severity is FindingSeverity.warn),
        "suggest_count": sum(1 for f in findings if f.severity is FindingSeverity.suggest),
        "info_count": sum(1 for f in findings if f.severity is FindingSeverity.info),
    }
    result: dict[str, Any] = {
        "summary": _summarize(findings, output.fuzz_count),
        "depth": depth,
        "stats": stats,
        "by_category": by_category,
    }
    result.update(output.result_extra)
    return result
