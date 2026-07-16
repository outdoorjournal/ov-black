"""The kernel graph: immutable nodes, edges, and one anchor.

Pure values — no SQLAlchemy, no I/O. The status/type/edge enums are shared with
``app.models.itinerary`` (they mirror the Postgres enums); the kernel owns the
*semantics*, the models own the persistence. Primitives in
``app.kernel.primitives`` are the only intended way a graph changes: each takes
a graph and returns a new one, so a ``Graph`` value is always structurally
valid and history is a sequence of values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.kernel.schedule import Schedule
from app.models.itinerary import EdgeType, NodeStatus, NodeType

# Types that never take a timeline slot. ``article`` mirrors
# app.services.node_kinds: a saved read lives in the Collection only.
NON_SCHEDULABLE_TYPES: frozenset[NodeType] = frozenset({NodeType.article})

# Statuses that represent a real-world commitment. Committed nodes are
# world-pinned (booking pins) and their schedules are locked against
# unschedule/unpin until the commitment is undone.
COMMITTED_STATUSES: frozenset[NodeStatus] = frozenset({NodeStatus.booked, NodeStatus.confirmed})


@dataclass(frozen=True)
class Provenance:
    """Where a node's content snapshot came from.

    ``date_sensitive`` marks snapshots quoted for a specific date (a flight
    fare, a fixed tour departure): moving such a node marks it
    ``needs_revalidation`` rather than blocking the move.
    """

    source: str
    source_id: str | None = None
    date_sensitive: bool = False


@dataclass(frozen=True)
class Node:
    id: str
    type: NodeType
    title: str = ""
    status: NodeStatus = NodeStatus.pending
    schedule: Schedule | None = None
    provenance: Provenance | None = None
    needs_revalidation: bool = False
    # Opaque card payload (locations, flight endpoints, snapshot fields …).
    # The kernel reads well-known keys (e.g. ``location`` coords for flight
    # feasibility) but never enforces shape.
    content: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    id: str
    from_id: str
    to_id: str
    type: EdgeType
    # Temporal constraint for ``follows`` edges: the successor must start at
    # least this many minutes after the predecessor ends. Analysis-only —
    # violating it is a finding, never a rejected mutation.
    min_gap_minutes: int | None = None


@dataclass(frozen=True)
class Graph:
    """One itinerary's structure. ``anchor_date`` is Day 1's calendar date."""

    anchor_date: date | None = None
    nodes: Mapping[str, Node] = field(default_factory=dict)
    edges: Mapping[str, Edge] = field(default_factory=dict)
    # Trip-level fields with no invariants of their own (title, brief, mood …).
    meta: Mapping[str, object] = field(default_factory=dict)


def fork(graph: Graph) -> Graph:
    """A fork is the same immutable value; divergence happens via primitives.

    Identity, persistence, and the fork/trunk relationship are service-layer
    concerns — the kernel only guarantees that applying primitives to a fork
    can never disturb the graph it was forked from.
    """
    return graph
