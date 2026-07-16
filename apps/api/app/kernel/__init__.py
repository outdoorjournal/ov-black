"""The itinerary kernel: a pure formalism for the travel graph.

Phase 1 of doc/itin-time.md. No DB, no HTTP, no clock reads — graphs in,
graphs out. ``primitives`` is the closed set of mutations (structural validity
enforced by construction), ``analysis`` is the read-only feasibility layer
(findings, never rejections), ``schedule`` is the wall-clock-canonical time
model that makes re-dating a trip a one-field change.
"""

from app.kernel.adapter import columns_from_schedule, schedule_from_columns
from app.kernel.analysis import Finding, GraphDiff, NodeChange, analyze, diff
from app.kernel.errors import KernelViolation
from app.kernel.graph import Edge, Graph, Node, Provenance, fork
from app.kernel.primitives import (
    RetimeReport,
    ScheduleReport,
    StatusReport,
    add_edge,
    add_node,
    clear_anchor,
    pin_node,
    remove_edge,
    remove_node,
    schedule_node,
    set_anchor,
    set_status,
    unpin_node,
    unschedule_node,
    update_node,
    update_trip_meta,
)
from app.kernel.schedule import (
    AbsoluteStamp,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    ResolvedSpan,
    Schedule,
    day_index,
    pin_schedule,
    relative,
    resolve_schedule,
    resolve_stamp,
    resolve_wall,
    unpin_schedule,
)

__all__ = [
    "AbsoluteStamp",
    "Edge",
    "Finding",
    "Graph",
    "GraphDiff",
    "KernelViolation",
    "Node",
    "NodeChange",
    "PinnedSchedule",
    "Provenance",
    "RelativeSchedule",
    "RelativeStamp",
    "ResolvedSpan",
    "RetimeReport",
    "Schedule",
    "ScheduleReport",
    "StatusReport",
    "add_edge",
    "add_node",
    "analyze",
    "clear_anchor",
    "columns_from_schedule",
    "day_index",
    "diff",
    "fork",
    "pin_node",
    "pin_schedule",
    "relative",
    "remove_edge",
    "remove_node",
    "resolve_schedule",
    "schedule_from_columns",
    "resolve_stamp",
    "resolve_wall",
    "schedule_node",
    "set_anchor",
    "set_status",
    "unpin_node",
    "unpin_schedule",
    "unschedule_node",
    "update_node",
    "update_trip_meta",
]
