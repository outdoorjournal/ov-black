"""Interaction-quality analysis over the itinerary graph (EVAL-2).

Where :mod:`ovb.invariants` guards structural integrity (statuses, dangling
edges, money), this module judges *how well a conversation landed on the
graph*: did intake actually capture timing and party, did a reschedule move
what it claimed, did a whole-trip shift carry every anchor-relative card, did
a flight land feasibly. Everything reads the Phase 4/5 kernel surfaces the
API already computes (``node.schedule`` resolved views + graph ``findings``)
— nothing re-derives time math client-side.

All functions are pure over already-fetched responses so both the eval
runner and pytest can call them without extra round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ovb._generated import models as gm
from ovb.invariants import Violation

# Statuses that pin a node to the calendar — a trip shift must NOT move these.
_PINNED_STATUSES = {"booked", "confirmed"}

_SEVERITY_RANK = {"info": 0, "warn": 1, "block": 2}


def enum_str(value: Any) -> str:
    """The plain-string form of a generated enum field ("" for None)."""
    if value is None:
        return ""
    return str(value.value if hasattr(value, "value") else value)


# ─────────────────────────────────────────────────────────────────────────────
# Resolved-schedule readers (Phase 4 views)
# ─────────────────────────────────────────────────────────────────────────────


def resolved_start_date(node: gm.NodeResponse) -> date | None:
    """The node's resolved local start date, or None while unresolvable."""
    sched = node.schedule
    if sched is None or sched.synthesized:
        return None
    return sched.start.date


def resolved_day_index(node: gm.NodeResponse) -> int | None:
    sched = node.schedule
    if sched is None or sched.synthesized:
        return None
    return sched.start.day_index


def scheduled_nodes(graph: gm.GraphResponse) -> list[gm.NodeResponse]:
    """Nodes genuinely placed on the timeline (non-synthesized schedule),
    excluding discarded ones."""
    return [
        n
        for n in graph.nodes
        if str(n.status) != "discarded" and n.schedule is not None and not n.schedule.synthesized
    ]


def nodes_of_type(graph: gm.GraphResponse, node_type: str) -> list[gm.NodeResponse]:
    return [n for n in graph.nodes if str(n.type) == node_type and str(n.status) != "discarded"]


def find_nodes(graph: gm.GraphResponse, title_contains: str) -> list[gm.NodeResponse]:
    needle = title_contains.lower()
    return [
        n for n in graph.nodes if needle in str(n.title).lower() and str(n.status) != "discarded"
    ]


def findings_at_or_above(graph: gm.GraphResponse, severity: str) -> list[gm.GraphFindingResponse]:
    floor = _SEVERITY_RANK.get(severity, 2)
    return [f for f in graph.findings or [] if _SEVERITY_RANK.get(enum_str(f.severity), 0) >= floor]


# ─────────────────────────────────────────────────────────────────────────────
# Shift analysis — "move the whole itinerary"
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ShiftReport:
    """How each commonly-scheduled node moved between two graph reads."""

    shifted: dict[str, int]  # node_id → delta days (relative nodes)
    held: list[str]  # pinned (booked/confirmed) nodes that stayed put
    broken: list[str]  # pinned nodes that MOVED (contract violation)
    lost_schedule: list[str]  # scheduled before, unresolvable after


def shift_report(before: gm.GraphResponse, after: gm.GraphResponse) -> ShiftReport:
    before_by_id = {str(n.id): n for n in before.nodes}
    shifted: dict[str, int] = {}
    held: list[str] = []
    broken: list[str] = []
    lost: list[str] = []
    for node in after.nodes:
        nid = str(node.id)
        prior = before_by_id.get(nid)
        if prior is None:
            continue
        d0 = resolved_start_date(prior)
        if d0 is None:
            continue
        d1 = resolved_start_date(node)
        if d1 is None:
            lost.append(nid)
            continue
        delta = (d1 - d0).days
        if str(prior.status) in _PINNED_STATUSES:
            (held if delta == 0 else broken).append(nid)
        elif delta != 0:
            shifted[nid] = delta
        else:
            shifted[nid] = 0
    return ShiftReport(shifted=shifted, held=held, broken=broken, lost_schedule=lost)


def uniform_shift_violations(
    before: gm.GraphResponse, after: gm.GraphResponse, *, expect_days: int
) -> list[Violation]:
    """Assert a whole-trip retime: every anchor-relative scheduled node moved by
    exactly ``expect_days``; every booked/confirmed node held; nothing lost its
    schedule."""
    report = shift_report(before, after)
    out: list[Violation] = []
    if not report.shifted:
        out.append(Violation("shift_no_nodes", "no scheduled nodes to compare across the shift"))
    off = {nid: d for nid, d in report.shifted.items() if d != expect_days}
    if off:
        out.append(
            Violation(
                "shift_nonuniform",
                f"expected every relative node to move {expect_days}d; off: {off}",
            )
        )
    if report.broken:
        out.append(
            Violation("shift_moved_pinned", f"booked/confirmed nodes moved: {report.broken}")
        )
    if report.lost_schedule:
        out.append(
            Violation("shift_lost_schedule", f"nodes lost their schedule: {report.lost_schedule}")
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding / interaction health — the post-conversation scorecard
# ─────────────────────────────────────────────────────────────────────────────


def _meta_blob(node: gm.NodeResponse) -> str:
    import json

    try:
        return json.dumps(node.metadata or {}, default=str).lower()
    except (TypeError, ValueError):
        return str(node.metadata).lower()


def flight_nodes(graph: gm.GraphResponse) -> list[gm.NodeResponse]:
    return nodes_of_type(graph, "flight")


def interaction_health(
    graph: gm.GraphResponse,
    *,
    party: gm.ItineraryPartyResponse | None = None,
) -> list[Violation]:
    """The graph-side scorecard for a traveler conversation.

    Every check reads state the conversation was *supposed* to produce, so a
    clean interaction yields ``[]`` and a messy one names what went wrong.
    Severity ``warn`` marks smells (duplicates, unresolved cards); ``error``
    marks contract breaks (kernel blocks, timing shapes that can't render).
    """
    out: list[Violation] = []
    itin = graph.itinerary

    # Timing must be a renderable shape: exact/window carry dates or a length;
    # a window with neither is a card the UI can't say anything about.
    kind = enum_str(itin.timing_kind)
    if kind == "exact" and (itin.date_start is None or itin.date_end is None):
        out.append(Violation("timing_exact_dateless", "timing_kind=exact without both dates"))
    if kind == "window" and itin.duration_nights is None and itin.date_start is None:
        out.append(
            Violation("timing_window_empty", "window timing with neither dates nor a length")
        )

    # Party: seated travelers must be distinct humans.
    if party is not None:
        names = [str(m.name).strip().lower() for m in party.members]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            out.append(Violation("party_duplicate", f"duplicate seated travelers: {sorted(dupes)}"))

    # Kernel judgements: any block finding means the plan physically fails.
    blocks = findings_at_or_above(graph, "block")
    for f in blocks:
        out.append(Violation("kernel_block", f"{f.code}: {f.message}"))

    # Articles are reading-list cards, never schedulable timeline entries.
    for node in nodes_of_type(graph, "article"):
        if node.schedulable:
            out.append(Violation("article_schedulable", f"article {node.id} is schedulable"))

    # A dated trip whose scheduled cards can't resolve is a kernel/agent slip.
    if itin.anchor_date is not None or itin.date_start is not None:
        for node in graph.nodes:
            if str(node.status) == "discarded" or not node.schedulable:
                continue
            sched = node.schedule
            if sched is not None and not sched.synthesized and sched.start.date is None:
                out.append(
                    Violation(
                        "schedule_unresolved",
                        f"node {node.id} ({node.title!r}) scheduled but date-unresolvable",
                        severity="warn",
                    )
                )

    # Duplicate live flights on the same route smell like re-proposal churn.
    flights = [n for n in flight_nodes(graph) if str(n.status) != "discarded"]
    seen_routes: dict[str, str] = {}
    for node in flights:
        meta = node.metadata or {}
        origin = meta.get("origin") or meta.get("depart_airport") or ""
        dest = meta.get("destination") or meta.get("arrive_airport") or ""
        route = f"{origin}→{dest}"
        day = str(resolved_start_date(node) or "")
        key = f"{route}@{day}"
        if route.strip("→") and key in seen_routes:
            out.append(
                Violation(
                    "flight_duplicate",
                    f"two live flights on {key}: {seen_routes[key]} and {node.id}",
                    severity="warn",
                )
            )
        else:
            seen_routes[key] = str(node.id)

    return out
