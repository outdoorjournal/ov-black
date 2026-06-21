"""Shallow Analyze runner — structural checks, no external calls (Phase 5 / B5).

Emits ``time`` (overlapping ranges on the timeline), ``cyclic`` (a cycle in the
``follows`` edges), and ``missing_required`` (a firmed-up node missing a field
its status needs) findings, and computes the ``fuzz_count`` planning-maturity
score. Sub-second and side-effect-free, so it's safe to run on every change.

:func:`collect` is reused by the standard runner, which layers physical
feasibility on top of these findings.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FindingSeverity, NodeStatus, NodeType
from app.services.analyze_runners.common import (
    Finding,
    GraphNode,
    RunOutput,
    load_edges,
    load_timeline_nodes,
)

# Statuses at or past which a node is "firmed up" and is expected to carry the
# fields the downstream pipeline (linearization, invoicing) needs.
_FIRM_STATUSES: frozenset[NodeStatus] = frozenset(
    {NodeStatus.approved, NodeStatus.booked, NodeStatus.confirmed}
)
# Node kinds that are bookable and therefore must carry a cost once firmed up
# (feeds the M005 money gate).
_BOOKABLE_TYPES: frozenset[NodeType] = frozenset(
    {NodeType.flight, NodeType.hotel, NodeType.experience, NodeType.meal}
)


def _time_overlap_findings(nodes: list[GraphNode]) -> list[Finding]:
    """Adjacent timed nodes whose ranges overlap (same implicit party).

    Nodes arrive ordered by ``starts_lower`` (nulls last); we walk consecutive
    fully-timed pairs and flag the later one when the earlier one hasn't ended.
    """
    timed = [n for n in nodes if n.starts_lower and n.starts_upper]
    findings: list[Finding] = []
    for prev, cur in zip(timed, timed[1:], strict=False):
        assert cur.starts_lower is not None and prev.starts_upper is not None
        # prev.starts_lower <= cur.starts_lower by sort order.
        if cur.starts_lower < prev.starts_upper:
            overlap_min = round((prev.starts_upper - cur.starts_lower).total_seconds() / 60)
            findings.append(
                Finding(
                    severity=FindingSeverity.warn,
                    category="time",
                    message=(
                        f"“{cur.title or 'Untitled'}” starts before "
                        f"“{prev.title or 'Untitled'}” ends "
                        f"(~{overlap_min} min overlap)."
                    ),
                    node_id=cur.node_id,
                    evidence={
                        "overlapping_node_id": str(prev.node_id),
                        "overlap_minutes": overlap_min,
                    },
                )
            )
    return findings


def _cycle_findings(
    edges: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]],
) -> list[Finding]:
    """Detect a directed cycle in the ``follows`` edges (DFS three-colour)."""
    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    for _eid, src, dst, etype in edges:
        if etype == "follows":
            adj.setdefault(src, []).append(dst)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[uuid.UUID, int] = {}
    cycle: list[uuid.UUID] = []

    def visit(node: uuid.UUID, stack: list[uuid.UUID]) -> bool:
        color[node] = GREY
        stack.append(node)
        for nxt in adj.get(node, ()):
            if color.get(nxt, WHITE) == GREY:
                start = stack.index(nxt)
                cycle.extend(stack[start:])
                return True
            if color.get(nxt, WHITE) == WHITE and visit(nxt, stack):
                return True
        stack.pop()
        color[node] = BLACK
        return False

    for src in list(adj.keys()):
        if color.get(src, WHITE) == WHITE and visit(src, []):
            break

    if not cycle:
        return []
    return [
        Finding(
            severity=FindingSeverity.block,
            category="cyclic",
            message="The itinerary's ordering edges form a cycle.",
            node_id=None,
            evidence={"cycle_node_ids": [str(n) for n in cycle]},
        )
    ]


def _missing_required_findings(nodes: list[GraphNode]) -> list[Finding]:
    """Firmed-up nodes missing a field their status needs."""
    findings: list[Finding] = []
    for n in nodes:
        if n.status not in _FIRM_STATUSES:
            continue
        if n.starts_lower is None:
            findings.append(
                Finding(
                    severity=FindingSeverity.suggest,
                    category="missing_required",
                    message=(
                        f"“{n.title or 'Untitled'}” is {n.status.value} but has no scheduled time."
                    ),
                    node_id=n.node_id,
                    evidence={
                        "field_path": "starts_at",
                        "status_required_for": n.status.value,
                    },
                )
            )
        if n.type in _BOOKABLE_TYPES and n.cost_amount is None:
            findings.append(
                Finding(
                    severity=FindingSeverity.suggest,
                    category="missing_required",
                    message=(f"“{n.title or 'Untitled'}” is {n.status.value} but carries no cost."),
                    node_id=n.node_id,
                    evidence={
                        "field_path": "cost_amount",
                        "status_required_for": n.status.value,
                    },
                )
            )
    return findings


def _fuzz_count(nodes: list[GraphNode]) -> int:
    """Nodes with no scheduled time or no location — the planning-maturity score."""
    return sum(1 for n in nodes if n.starts_lower is None or not n.has_point)


async def collect(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    scope: dict[str, Any] | None = None,
) -> tuple[list[Finding], list[GraphNode], int]:
    """Run the structural checks and return ``(findings, nodes, fuzz_count)``.

    Returns the loaded nodes so the standard runner can layer drive-time
    feasibility without re-querying.
    """
    nodes = await load_timeline_nodes(session, itinerary_id=itinerary_id, scope=scope)
    edges = await load_edges(session, itinerary_id=itinerary_id)
    findings = (
        _time_overlap_findings(nodes) + _cycle_findings(edges) + _missing_required_findings(nodes)
    )
    return findings, nodes, _fuzz_count(nodes)


async def run(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    scope: dict[str, Any] | None = None,
) -> RunOutput:
    findings, nodes, fuzz = await collect(session, itinerary_id=itinerary_id, scope=scope)
    return RunOutput(findings=findings, node_count=len(nodes), fuzz_count=fuzz)


__all__ = ["collect", "run"]
