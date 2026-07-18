"""Read-only analysis over a kernel graph: findings, never rejections.

Structural validity is the primitives' job; everything here is a judgement
about a graph that is already legal to hold — overlaps, follows-gaps, flight
feasibility (ported from apps/agent flight_timing, now running on true resolved
instants so cross-zone ordering is exact), lodging windows (check-in
reachability, checkout-morning conflicts), stale snapshots, and diffs between
two graphs.

An undated trip is analyzed on a provisional calendar: ordering, overlaps, and
gaps are meaningful (every relative stamp shifts by the same anchor), while
DST-specific instants only become exact once the trip is pinned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt

from app.kernel.graph import Graph, Node
from app.kernel.presence import LODGING_TYPES
from app.kernel.schedule import (
    AbsoluteStamp,
    RelativeStamp,
    ResolvedSpan,
    resolve_schedule,
    resolve_wall,
)
from app.models.itinerary import EdgeType, NodeStatus, NodeType

# Types that mean "the traveler must physically be at an event" — these anchor
# the flight-feasibility floor and the overlap read. Transit kinds don't (a
# drive is usually the airport transfer itself); notes and articles are not
# commitments. Lodging is deliberately absent: a stay is presence, not an
# event — its span is *supposed* to contain every dinner and tour of the trip,
# and the only moments that carry constraints (check-in reachability, checkout
# morning) get their own findings in ``lodging_findings``.
_EVENT_TYPES = frozenset(
    {NodeType.experience, NodeType.meal, NodeType.free_time, NodeType.destination}
)

# Margins below which a physically-possible connection is still called out as
# tight. Warnings only — the block fires solely on impossibility.
_ARRIVAL_MARGIN_MIN = 180
_DEPARTURE_MARGIN_MIN = 180

# A lone flight is a trip bookend only if one endpoint is far from the trip's
# base; nearer is an internal hop the arrival/departure floor shouldn't touch.
_BOOKEND_FAR_KM = 1000.0

# Any date works for an undated trip: relative stamps all shift together, so
# ordering and gaps are anchor-invariant.
_PROVISIONAL_ANCHOR = date(2001, 1, 1)


@dataclass(frozen=True)
class Finding:
    # "flight_infeasible" | "flight_tight" | "overlap" | "follows_gap" |
    # "lodging_checkin_late" | "lodging_checkout_conflict" | "stale"
    code: str
    severity: str  # "block" | "warn" | "info"
    message: str
    node_ids: tuple[str, ...]


def effective_anchor(graph: Graph) -> date:
    return graph.anchor_date if graph.anchor_date is not None else _PROVISIONAL_ANCHOR


def _span(node: Node, anchor: date) -> ResolvedSpan | None:
    if node.schedule is None or node.status is NodeStatus.discarded:
        return None
    return resolve_schedule(node.schedule, anchor)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%b %d %H:%M")


def _coords(value: object) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    lat, lng = value.get("lat"), value.get("lng")
    if isinstance(lat, int | float) and isinstance(lng, int | float):
        return float(lat), float(lng)
    return None


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


# ── overlaps ─────────────────────────────────────────────────────────────────


def _intentional_pairs(graph: Graph) -> set[frozenset[str]]:
    """Node pairs whose co-timing is deliberate (alternatives, groupings)."""
    return {
        frozenset({e.from_id, e.to_id})
        for e in graph.edges.values()
        if e.type in (EdgeType.alternative_to, EdgeType.grouped_with)
    }


def overlap_findings(graph: Graph) -> list[Finding]:
    """Event commitments whose resolved spans intersect — unless the graph
    says the overlap is intentional (alternative_to / grouped_with edges).
    Lodging never participates: a multi-night stay containing the trip's
    dinners is the point of a hotel, not a conflict."""
    anchor = effective_anchor(graph)
    intentional = _intentional_pairs(graph)
    spanned: list[tuple[Node, datetime, datetime]] = []
    for node in graph.nodes.values():
        if node.type not in _EVENT_TYPES:
            continue
        span = _span(node, anchor)
        if span is None or span.end is None:
            continue
        spanned.append((node, span.start, span.end))
    spanned.sort(key=lambda item: item[1])

    findings: list[Finding] = []
    for i, (a, a_start, a_end) in enumerate(spanned):
        for b, b_start, _b_end in spanned[i + 1 :]:
            if b_start >= a_end:
                break
            if frozenset({a.id, b.id}) in intentional:
                continue
            findings.append(
                Finding(
                    code="overlap",
                    severity="warn",
                    message=(
                        f"'{a.title}' ({_fmt(a_start)}–{_fmt(a_end)}) overlaps "
                        f"'{b.title}' (starts {_fmt(b_start)})"
                    ),
                    node_ids=(a.id, b.id),
                )
            )
    return findings


# ── follows-edge temporal constraints ────────────────────────────────────────


def follows_findings(graph: Graph) -> list[Finding]:
    anchor = effective_anchor(graph)
    findings: list[Finding] = []
    for edge in graph.edges.values():
        if edge.type is not EdgeType.follows or edge.min_gap_minutes is None:
            continue
        prev = graph.nodes.get(edge.from_id)
        nxt = graph.nodes.get(edge.to_id)
        if prev is None or nxt is None:
            continue
        prev_span = _span(prev, anchor)
        next_span = _span(nxt, anchor)
        if prev_span is None or prev_span.end is None or next_span is None:
            continue
        required = prev_span.end + timedelta(minutes=edge.min_gap_minutes)
        if next_span.start < required:
            short = int((required - next_span.start).total_seconds() // 60)
            findings.append(
                Finding(
                    code="follows_gap",
                    severity="warn",
                    message=(
                        f"'{nxt.title}' starts {_fmt(next_span.start)}, {short} min inside the "
                        f"{edge.min_gap_minutes} min gap required after '{prev.title}' ends "
                        f"({_fmt(prev_span.end)})"
                    ),
                    node_ids=(prev.id, nxt.id),
                )
            )
    return findings


# ── flight feasibility (the hard floor) ──────────────────────────────────────


@dataclass(frozen=True)
class _Ground:
    start: datetime
    end: datetime
    node: Node


@dataclass(frozen=True)
class _Leg:
    node: Node
    depart: datetime
    arrive: datetime | None
    from_loc: tuple[float, float] | None
    to_loc: tuple[float, float] | None


def _ground_bounds(grounds: list[_Ground]) -> tuple[_Ground | None, _Ground | None]:
    if not grounds:
        return None, None
    return min(grounds, key=lambda g: g.start), max(grounds, key=lambda g: g.end)


def _base_location(grounds: list[_Ground]) -> tuple[float, float] | None:
    for ground in sorted(grounds, key=lambda g: g.start):
        coords = _coords(ground.node.content.get("location"))
        if coords is not None:
            return coords
    return None


def _classify_lone(leg: _Leg, base: tuple[float, float] | None) -> tuple[_Leg | None, _Leg | None]:
    """A single flight is placed by direction versus the trip base: coming from
    far = the way in, going far = the way home, neither = internal hop."""
    if base is None:
        return None, None
    from_far = leg.from_loc is not None and _haversine_km(leg.from_loc, base) > _BOOKEND_FAR_KM
    to_far = leg.to_loc is not None and _haversine_km(leg.to_loc, base) > _BOOKEND_FAR_KM
    if from_far and not to_far:
        return leg, None
    if to_far and not from_far:
        return None, leg
    return None, None


def flight_findings(graph: Graph) -> list[Finding]:
    """The outbound must land before the first event commitment begins; the
    return must depart after the last one ends. Blocks fire only on physical
    impossibility; tight margins warn. Resolution gives true instants, so a
    Detroit departure and an Athens arrival compare exactly.

    Lodging is not part of the floor: a check-in is a window, not a start you
    can miss (``lodging_findings`` judges it against the desk cutoff), and a
    checkout is not an end you must stay for — an early return flight before
    checkout time is normal, not infeasible. Lodging still anchors the base
    location, since the hotel is usually the best-placed node.
    """
    anchor = effective_anchor(graph)
    grounds = [
        _Ground(span.start, span.end if span.end is not None else span.start, node)
        for node in graph.nodes.values()
        if node.type in _EVENT_TYPES and (span := _span(node, anchor)) is not None
    ]
    lodgings = [
        _Ground(span.start, span.end if span.end is not None else span.start, node)
        for node in graph.nodes.values()
        if node.type in LODGING_TYPES and (span := _span(node, anchor)) is not None
    ]
    first, last = _ground_bounds(grounds)
    if first is None or last is None:
        return []

    legs: list[_Leg] = []
    for node in graph.nodes.values():
        if node.type is not NodeType.flight:
            continue
        span = _span(node, anchor)
        if span is None:
            continue
        legs.append(
            _Leg(
                node=node,
                depart=span.start,
                arrive=span.end,
                from_loc=_coords(node.content.get("from_location")),
                to_loc=_coords(node.content.get("to_location")),
            )
        )
    if not legs:
        return []

    if len(legs) >= 2:
        # Round trip / multi-city bookends by extremal timing: earliest arrival
        # is the way in, latest departure the way home; internal hops sit
        # between both extremes and are never selected.
        with_arrival = [leg for leg in legs if leg.arrive is not None]
        outbound = (
            min(with_arrival, key=lambda leg: leg.arrive)  # type: ignore[arg-type, return-value]
            if with_arrival
            else None
        )
        inbound: _Leg | None = max(legs, key=lambda leg: leg.depart)
    else:
        outbound, inbound = _classify_lone(legs[0], _base_location(grounds + lodgings))

    findings: list[Finding] = []
    if outbound is not None and outbound.arrive is not None:
        arrive = outbound.arrive
        if arrive >= first.start:
            findings.append(
                Finding(
                    code="flight_infeasible",
                    severity="block",
                    message=(
                        f"Outbound '{outbound.node.title}' arrives {_fmt(arrive)} — at or after "
                        f"the first scheduled item '{first.node.title}' begins "
                        f"({_fmt(first.start)}). The traveler would still be in transit."
                    ),
                    node_ids=(outbound.node.id, first.node.id),
                )
            )
        elif first.start - arrive < timedelta(minutes=_ARRIVAL_MARGIN_MIN):
            margin = int((first.start - arrive).total_seconds() // 60)
            findings.append(
                Finding(
                    code="flight_tight",
                    severity="warn",
                    message=(
                        f"Outbound '{outbound.node.title}' arrives {_fmt(arrive)}, only "
                        f"{margin} min before '{first.node.title}' at {_fmt(first.start)}."
                    ),
                    node_ids=(outbound.node.id, first.node.id),
                )
            )

    if inbound is not None:
        depart = inbound.depart
        if depart <= last.end:
            findings.append(
                Finding(
                    code="flight_infeasible",
                    severity="block",
                    message=(
                        f"Return '{inbound.node.title}' departs {_fmt(depart)} — at or before "
                        f"the last scheduled item '{last.node.title}' ends ({_fmt(last.end)}). "
                        f"The traveler can't make the gate."
                    ),
                    node_ids=(inbound.node.id, last.node.id),
                )
            )
        elif depart - last.end < timedelta(minutes=_DEPARTURE_MARGIN_MIN):
            margin = int((depart - last.end).total_seconds() // 60)
            findings.append(
                Finding(
                    code="flight_tight",
                    severity="warn",
                    message=(
                        f"Return '{inbound.node.title}' departs {_fmt(depart)}, only "
                        f"{margin} min after '{last.node.title}' ends ({_fmt(last.end)})."
                    ),
                    node_ids=(inbound.node.id, last.node.id),
                )
            )

    return findings


# ── lodging: the first night is a window, the last morning a soft deadline ───

# Arrivals this long after the check-in date's local midnight still belong to
# the check-in night (covers a red-eye landing at 01:30 the next local date).
_CHECKIN_NIGHT_HOURS = 36


def _cutoff_wall(value: object) -> time | None:
    """Parse a ``check_in_cutoff`` card value ("HH:MM"); None on anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else None


def _stamp_local_date(stamp: RelativeStamp | AbsoluteStamp, anchor: date) -> date:
    if isinstance(stamp, AbsoluteStamp):
        return stamp.on
    return anchor + timedelta(days=stamp.day_offset)


def lodging_findings(graph: Graph) -> list[Finding]:
    """A stay's two real timeline moments, judged as windows — never blocks.

    Check-in reachability: the first night is the only one you must *get to*,
    and even that is a window. When the card carries a ``check_in_cutoff``
    ("HH:MM" wall time at the property; absent means a 24h desk and no
    finding), and every flight landing around the check-in night arrives
    after it, the desk may be closed on the traveler.

    Checkout conflict: an event still running at checkout time on the last
    morning means luggage or late-checkout logistics an advisor should see.
    """
    anchor = effective_anchor(graph)
    arrivals: list[tuple[datetime, Node]] = []
    for node in graph.nodes.values():
        if node.type is not NodeType.flight:
            continue
        span = _span(node, anchor)
        if span is not None and span.end is not None:
            arrivals.append((span.end, node))

    findings: list[Finding] = []
    for node in graph.nodes.values():
        if node.type not in LODGING_TYPES:
            continue
        span = _span(node, anchor)
        if span is None:
            continue

        cutoff_wall = _cutoff_wall(node.content.get("check_in_cutoff"))
        if cutoff_wall is not None and arrivals:
            checkin_stamp = node.schedule.start if node.schedule is not None else None
            if checkin_stamp is not None:
                checkin_date = _stamp_local_date(checkin_stamp, anchor)
                tz_name = checkin_stamp.tz_name
                cutoff = resolve_wall(checkin_date, cutoff_wall, tz_name)
                if cutoff < span.start:  # an after-midnight cutoff (e.g. 01:00)
                    cutoff = resolve_wall(checkin_date + timedelta(days=1), cutoff_wall, tz_name)
                night_open = resolve_wall(checkin_date, time(0, 0), tz_name)
                night_close = night_open + timedelta(hours=_CHECKIN_NIGHT_HOURS)
                night_arrivals = [a for a in arrivals if night_open <= a[0] < night_close]
                if night_arrivals:
                    earliest, leg = min(night_arrivals, key=lambda a: a[0])
                    if earliest > cutoff:
                        late = int((earliest - cutoff).total_seconds() // 60)
                        findings.append(
                            Finding(
                                code="lodging_checkin_late",
                                severity="warn",
                                message=(
                                    f"'{leg.title}' lands {_fmt(earliest)}, {late} min after "
                                    f"'{node.title}' stops check-in ({_fmt(cutoff)}) — the desk "
                                    f"may be closed on arrival night."
                                ),
                                node_ids=(node.id, leg.id),
                            )
                        )

        checkout = span.end
        if checkout is None:
            continue
        for other in graph.nodes.values():
            if other.type not in _EVENT_TYPES:
                continue
            ospan = _span(other, anchor)
            if ospan is None or ospan.end is None:
                continue
            if span.start <= ospan.start < checkout < ospan.end:
                findings.append(
                    Finding(
                        code="lodging_checkout_conflict",
                        severity="warn",
                        message=(
                            f"'{other.title}' ({_fmt(ospan.start)}–{_fmt(ospan.end)}) is still "
                            f"running when '{node.title}' checkout closes ({_fmt(checkout)}) — "
                            f"plan luggage or a late checkout."
                        ),
                        node_ids=(node.id, other.id),
                    )
                )
    return findings


# ── staleness ────────────────────────────────────────────────────────────────


def stale_findings(graph: Graph) -> list[Finding]:
    return [
        Finding(
            code="stale",
            severity="info",
            message=f"'{node.title}' moved after its snapshot was quoted — re-check availability",
            node_ids=(node.id,),
        )
        for node in graph.nodes.values()
        if node.needs_revalidation and node.status is not NodeStatus.discarded
    ]


def analyze(graph: Graph) -> tuple[Finding, ...]:
    """The full feasibility read: every finding, never an exception."""
    return tuple(
        flight_findings(graph)
        + lodging_findings(graph)
        + overlap_findings(graph)
        + follows_findings(graph)
        + stale_findings(graph)
    )


# ── diff ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeChange:
    node_id: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class GraphDiff:
    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    changed_nodes: tuple[NodeChange, ...]
    added_edges: tuple[str, ...]
    removed_edges: tuple[str, ...]
    anchor_changed: bool

    @property
    def empty(self) -> bool:
        return not (
            self.added_nodes
            or self.removed_nodes
            or self.changed_nodes
            or self.added_edges
            or self.removed_edges
            or self.anchor_changed
        )


_DIFF_FIELDS = ("title", "status", "schedule", "content", "needs_revalidation")


def diff(base: Graph, other: Graph) -> GraphDiff:
    """What ``other`` changed relative to ``base`` — the substrate a fork
    reconcile selects from."""
    changed: list[NodeChange] = []
    for node_id in sorted(base.nodes.keys() & other.nodes.keys()):
        a, b = base.nodes[node_id], other.nodes[node_id]
        fields = tuple(f for f in _DIFF_FIELDS if getattr(a, f) != getattr(b, f))
        if fields:
            changed.append(NodeChange(node_id=node_id, fields=fields))
    return GraphDiff(
        added_nodes=tuple(sorted(other.nodes.keys() - base.nodes.keys())),
        removed_nodes=tuple(sorted(base.nodes.keys() - other.nodes.keys())),
        changed_nodes=tuple(changed),
        added_edges=tuple(sorted(other.edges.keys() - base.edges.keys())),
        removed_edges=tuple(sorted(base.edges.keys() - other.edges.keys())),
        anchor_changed=base.anchor_date != other.anchor_date,
    )
