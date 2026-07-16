"""The closed set of graph mutations.

Every planning activity in the product decomposes onto these functions (see the
activity → primitive table in doc/itin-time.md). Each primitive takes a
``Graph`` and returns a new one — structural invariants are enforced here and
only here, by raising ``KernelViolation``; temporal feasibility is never
enforced, it is reported (``app.kernel.analysis``) or recorded on the node
(``needs_revalidation``).

Consequence-bearing primitives return a report alongside the graph. The report
is the affordance: "a retime can't move pinned nodes" reaches the caller as
``RetimeReport.held_pinned``, not as a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.kernel.errors import KernelViolation
from app.kernel.graph import (
    COMMITTED_STATUSES,
    NON_SCHEDULABLE_TYPES,
    Edge,
    Graph,
    Node,
)
from app.kernel.schedule import (
    PinnedSchedule,
    RelativeSchedule,
    Schedule,
    pin_schedule,
    unpin_schedule,
)
from app.models.itinerary import NodeStatus

# Legal status transitions. ``pending`` is the single pre-firmed default
# (0043); demotion out of booked/confirmed is legal because advisors edit
# real-world mistakes, and it un-pins (see set_status).
_LEGAL_TRANSITIONS: dict[NodeStatus, frozenset[NodeStatus]] = {
    NodeStatus.pending: frozenset({NodeStatus.approved, NodeStatus.booked, NodeStatus.discarded}),
    NodeStatus.approved: frozenset({NodeStatus.pending, NodeStatus.booked, NodeStatus.discarded}),
    NodeStatus.booked: frozenset({NodeStatus.confirmed, NodeStatus.pending, NodeStatus.discarded}),
    NodeStatus.confirmed: frozenset({NodeStatus.booked, NodeStatus.pending, NodeStatus.discarded}),
    NodeStatus.discarded: frozenset({NodeStatus.pending}),
}


def _require_node(graph: Graph, node_id: str) -> Node:
    node = graph.nodes.get(node_id)
    if node is None:
        raise KernelViolation("unknown_node", f"node {node_id!r} is not in the graph")
    return node


def _with_node(graph: Graph, node: Node) -> Graph:
    nodes = dict(graph.nodes)
    nodes[node.id] = node
    return replace(graph, nodes=nodes)


# ── content ──────────────────────────────────────────────────────────────────


def add_node(graph: Graph, node: Node) -> Graph:
    if node.id in graph.nodes:
        raise KernelViolation("duplicate_node", f"node {node.id!r} already exists")
    if node.schedule is not None and node.type in NON_SCHEDULABLE_TYPES:
        raise KernelViolation(
            "unschedulable_type", f"{node.type.value} nodes never take a timeline slot"
        )
    return _with_node(graph, node)


def update_node(
    graph: Graph,
    node_id: str,
    *,
    title: str | None = None,
    content: dict[str, object] | None = None,
) -> Graph:
    """Patch a node's content. A fresh content snapshot clears the stale mark —
    re-quoting against the provider is exactly an ``update_node`` with new
    content (doc/itin-time.md, "Moves can invalidate content")."""
    node = _require_node(graph, node_id)
    if title is not None:
        node = replace(node, title=title)
    if content is not None:
        node = replace(node, content=content, needs_revalidation=False)
    return _with_node(graph, node)


def remove_node(graph: Graph, node_id: str) -> Graph:
    """Remove a node and cascade its incident edges (dangling edges cannot
    exist, by construction)."""
    _require_node(graph, node_id)
    nodes = {nid: n for nid, n in graph.nodes.items() if nid != node_id}
    edges = {eid: e for eid, e in graph.edges.items() if node_id not in (e.from_id, e.to_id)}
    return replace(graph, nodes=nodes, edges=edges)


def add_edge(graph: Graph, edge: Edge) -> Graph:
    if edge.id in graph.edges:
        raise KernelViolation("duplicate_edge", f"edge {edge.id!r} already exists")
    if edge.from_id == edge.to_id:
        raise KernelViolation("self_edge", "an edge cannot connect a node to itself")
    _require_node(graph, edge.from_id)
    _require_node(graph, edge.to_id)
    edges = dict(graph.edges)
    edges[edge.id] = edge
    return replace(graph, edges=edges)


def remove_edge(graph: Graph, edge_id: str) -> Graph:
    if edge_id not in graph.edges:
        raise KernelViolation("unknown_edge", f"edge {edge_id!r} is not in the graph")
    return replace(graph, edges={eid: e for eid, e in graph.edges.items() if eid != edge_id})


def update_trip_meta(graph: Graph, patch: dict[str, object]) -> Graph:
    """Trip-level fields (title, brief, mood, hero …) — thin, but every
    itinerary write flows through one door."""
    meta = dict(graph.meta)
    meta.update(patch)
    return replace(graph, meta=meta)


# ── status ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatusReport:
    """Schedule side effects of a status change, surfaced to the caller."""

    auto_pinned: bool = False
    auto_unpinned: bool = False


def set_status(graph: Graph, node_id: str, status: NodeStatus) -> tuple[Graph, StatusReport]:
    """Change a node's lifecycle status under the legal-transition matrix.

    Pinnedness is a lifecycle property: entering booked/confirmed promotes a
    relative schedule to world-pinned (nothing bookable exists without a date,
    so booking on an undated trip is a violation); leaving the committed
    statuses demotes a pinned schedule back to anchor-relative when an anchor
    exists to demote against.
    """
    node = _require_node(graph, node_id)
    if status == node.status:
        return graph, StatusReport()
    if status not in _LEGAL_TRANSITIONS[node.status]:
        raise KernelViolation(
            "illegal_transition", f"{node.status.value} → {status.value} is not a legal transition"
        )

    report = StatusReport()
    entering = status in COMMITTED_STATUSES and node.status not in COMMITTED_STATUSES
    leaving = node.status in COMMITTED_STATUSES and status not in COMMITTED_STATUSES
    schedule = node.schedule
    if entering and isinstance(schedule, RelativeSchedule):
        if graph.anchor_date is None:
            raise KernelViolation(
                "book_undated",
                "cannot book a date-relative node on an undated trip — set the anchor first",
            )
        schedule = pin_schedule(schedule, graph.anchor_date)
        report = replace(report, auto_pinned=True)
    if leaving and isinstance(schedule, PinnedSchedule) and graph.anchor_date is not None:
        schedule = unpin_schedule(schedule, graph.anchor_date)
        report = replace(report, auto_unpinned=True)

    return _with_node(graph, replace(node, status=status, schedule=schedule)), report


# ── scheduling ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduleReport:
    marked_stale: bool = False


def schedule_node(graph: Graph, node_id: str, schedule: Schedule) -> tuple[Graph, ScheduleReport]:
    """Place (or move) a node on the timeline.

    Moving a node whose content snapshot is date-sensitive succeeds and marks
    it ``needs_revalidation`` — the move is structural, the stale quote is
    data. Passing a ``PinnedSchedule`` is the explicit advisor pin for
    fixed-date events; committed nodes must stay world-pinned.
    """
    node = _require_node(graph, node_id)
    if node.type in NON_SCHEDULABLE_TYPES:
        raise KernelViolation(
            "unschedulable_type", f"{node.type.value} nodes never take a timeline slot"
        )
    if node.status in COMMITTED_STATUSES and isinstance(schedule, RelativeSchedule):
        raise KernelViolation(
            "committed_unpin", "a booked/confirmed node stays world-pinned; demote it first"
        )
    stale = (
        node.provenance is not None
        and node.provenance.date_sensitive
        and node.schedule is not None
        and node.schedule != schedule
    )
    updated = replace(node, schedule=schedule, needs_revalidation=node.needs_revalidation or stale)
    return _with_node(graph, updated), ScheduleReport(marked_stale=stale)


def unschedule_node(graph: Graph, node_id: str) -> Graph:
    """Back to the Collection. Committed nodes are locked by their commitment."""
    node = _require_node(graph, node_id)
    if node.status in COMMITTED_STATUSES:
        raise KernelViolation(
            "committed_unschedule", "cancel the booking before unscheduling this node"
        )
    return _with_node(graph, replace(node, schedule=None))


def pin_node(graph: Graph, node_id: str) -> Graph:
    """Explicit pin (fixed-date event, no booking required)."""
    node = _require_node(graph, node_id)
    if isinstance(node.schedule, PinnedSchedule):
        return graph
    if not isinstance(node.schedule, RelativeSchedule):
        raise KernelViolation("pin_unscheduled", "only a scheduled node can be pinned")
    if graph.anchor_date is None:
        raise KernelViolation(
            "pin_undated", "cannot pin day-offsets to the world without an anchor date"
        )
    return _with_node(graph, replace(node, schedule=pin_schedule(node.schedule, graph.anchor_date)))


def unpin_node(graph: Graph, node_id: str) -> Graph:
    node = _require_node(graph, node_id)
    if isinstance(node.schedule, RelativeSchedule):
        return graph
    if not isinstance(node.schedule, PinnedSchedule):
        raise KernelViolation("unpin_unscheduled", "only a scheduled node can be unpinned")
    if node.status in COMMITTED_STATUSES:
        raise KernelViolation(
            "committed_unpin", "a booked/confirmed node stays world-pinned; demote it first"
        )
    if graph.anchor_date is None:
        raise KernelViolation("unpin_undated", "cannot derive day-offsets without an anchor date")
    return _with_node(
        graph, replace(node, schedule=unpin_schedule(node.schedule, graph.anchor_date))
    )


# ── the anchor ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RetimeReport:
    """What an anchor change did — the caller's affordance, not a rejection.

    ``moved`` — relative nodes whose resolved dates changed (their stored form
    did not: that is the point of the model). ``held_pinned`` — world-pinned
    nodes the retime deliberately did not move. ``marked_stale`` — moved nodes
    whose date-sensitive snapshots now need re-checking with their provider.
    Feasibility findings against the new dates come from ``analysis.analyze``,
    which callers run on the returned graph.
    """

    moved: tuple[str, ...] = ()
    held_pinned: tuple[str, ...] = ()
    marked_stale: tuple[str, ...] = ()


def set_anchor(graph: Graph, anchor_date: date | None) -> tuple[Graph, RetimeReport]:
    """Set, move, or clear (``None``) the trip's Day-1 calendar date.

    One field changes; relative schedules are untouched by construction.
    """
    if anchor_date == graph.anchor_date:
        return graph, RetimeReport()

    moved: list[str] = []
    held: list[str] = []
    stale: list[str] = []
    nodes = dict(graph.nodes)
    for node in graph.nodes.values():
        if isinstance(node.schedule, PinnedSchedule):
            held.append(node.id)
        elif isinstance(node.schedule, RelativeSchedule):
            moved.append(node.id)
            if (
                node.provenance is not None
                and node.provenance.date_sensitive
                and not node.needs_revalidation
            ):
                stale.append(node.id)
                nodes[node.id] = replace(node, needs_revalidation=True)

    updated = replace(graph, anchor_date=anchor_date, nodes=nodes)
    return updated, RetimeReport(
        moved=tuple(moved), held_pinned=tuple(held), marked_stale=tuple(stale)
    )


def clear_anchor(graph: Graph) -> tuple[Graph, RetimeReport]:
    return set_anchor(graph, None)
