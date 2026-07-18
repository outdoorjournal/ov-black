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
from app.kernel.placement import (
    follows_order,
    synthesize_placements,
    trip_default_zone,
)
from app.kernel.presence import LODGING_TYPES, NightLodging, lodging_at, nightly_lodging
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
    ResolvedScheduleView,
    ResolvedSpan,
    ResolvedStampView,
    Schedule,
    day_index,
    pin_schedule,
    relative,
    resolve_schedule,
    resolve_stamp,
    resolve_view,
    resolve_wall,
    unpin_schedule,
)

__all__ = [
    "AbsoluteStamp",
    "add_edge",
    "add_node",
    "analyze",
    "clear_anchor",
    "columns_from_schedule",
    "day_index",
    "diff",
    "Edge",
    "Finding",
    "follows_order",
    "fork",
    "Graph",
    "GraphDiff",
    "KernelViolation",
    "lodging_at",
    "LODGING_TYPES",
    "NightLodging",
    "nightly_lodging",
    "Node",
    "NodeChange",
    "pin_node",
    "pin_schedule",
    "PinnedSchedule",
    "Provenance",
    "relative",
    "RelativeSchedule",
    "RelativeStamp",
    "remove_edge",
    "remove_node",
    "resolve_schedule",
    "resolve_stamp",
    "resolve_view",
    "resolve_wall",
    "ResolvedScheduleView",
    "ResolvedSpan",
    "ResolvedStampView",
    "RetimeReport",
    "Schedule",
    "schedule_from_columns",
    "schedule_node",
    "ScheduleReport",
    "set_anchor",
    "set_status",
    "StatusReport",
    "synthesize_placements",
    "trip_default_zone",
    "unpin_node",
    "unpin_schedule",
    "unschedule_node",
    "update_node",
    "update_trip_meta",
]
