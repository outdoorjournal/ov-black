"""Physical-feasibility guard for a flight against the plan it lands on.

The concierge chooses a flight by its clock, not its price (see the flight
protocol in ``prompts/planning.py``). That's a judgement call the model can —
and once did — talk itself past: it proposed a Detroit→Thessaloniki outbound
that *arrived* the morning **after** the plan's first scheduled item began, then
narrated the miss away as "landing on arrival day works perfectly." The traveler
was booked onto the mountain at 15:00 while still over the Atlantic.

This module is the hard floor under that judgement. It is deliberately
physics-only: a ``block`` fires solely when a leg is *impossible* no matter the
ground transfer —

* an **outbound** that arrives at or after the first dated commitment begins, or
* a **return** that departs at or before the last dated commitment ends.

No buffer is baked into the block (a buffer would risk false positives on a
tight-but-doable connection); the buffer/transfer margin stays the model's job,
now backed by this floor. ``warn`` conflicts flag a tight-but-possible margin so
the caller can surface them without blocking.

Pure and side-effect free: it takes the itinerary's ``nodes`` (the
``get_itinerary`` envelope shape) and returns structured conflicts. The
``propose_flight`` tool runs it after a write and rolls the leg back on a block.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

# Types that mean "the traveler must physically be on the ground." A ``flight``
# is transit; a ``drive`` is almost always the airport transfer itself (it
# *follows* the arrival), so neither anchors the arrival test. ``article`` nodes
# are dateless reading-list items.
_ANCHOR_TYPES = frozenset(
    {"experience", "hotel", "meal", "free_time", "destination", "activity"}
)

# Minutes of margin below which a physically-possible connection is still called
# out as tight (``warn``). International arrival: deplane + immigration + bags +
# the transfer to the first stop. Return: reach the airport + check-in +
# security. These gate warnings only — never the block.
_ARRIVAL_MARGIN_MIN = 180
_DEPARTURE_MARGIN_MIN = 180

# A lone flight is a trip bookend (an outbound/return worth guarding) only if one
# endpoint is far from the trip's base — a real way-in/way-home hop for this
# clientele crosses regions. Nearer than this it's an internal segment the
# arrival/departure floor shouldn't touch. Round trips don't need this: they're
# classified by extremal timing (earliest arrival in, latest departure out).
_BOOKEND_FAR_KM = 1000.0


@dataclass(frozen=True)
class FlightConflict:
    """One feasibility problem tying a flight node to a scheduled commitment."""

    node_id: str
    leg: str  # "outbound" | "return"
    severity: str  # "block" | "warn"
    detail: str


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%b %d %H:%M")


def _coords(loc: object) -> tuple[float, float] | None:
    if not isinstance(loc, dict):
        return None
    lat, lng = loc.get("lat"), loc.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)
    return None


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def _base_location(nodes: list[dict]) -> tuple[float, float] | None:
    """The trip's on-the-ground anchor point — the first dated item with coords."""
    dated = [
        (_parse(n.get("starts_at")), n)
        for n in nodes
        if n.get("type") in _ANCHOR_TYPES and _parse(n.get("starts_at")) is not None
    ]
    for _, node in sorted(dated, key=lambda pair: pair[0]):  # type: ignore[arg-type,return-value]
        coords = _coords((node.get("metadata") or {}).get("location"))
        if coords is not None:
            return coords
    return None


@dataclass(frozen=True)
class _Anchor:
    start: datetime
    end: datetime
    node: dict


def _anchor_bounds(nodes: list[dict]) -> tuple[_Anchor | None, _Anchor | None]:
    """Earliest-starting dated commitment and latest-ending one."""
    anchors: list[_Anchor] = []
    for node in nodes:
        if node.get("type") not in _ANCHOR_TYPES:
            continue
        start = _parse(node.get("starts_at"))
        if start is None:
            continue
        duration = node.get("duration_minutes") or 0
        anchors.append(_Anchor(start, start + timedelta(minutes=int(duration)), node))
    if not anchors:
        return None, None
    first = min(anchors, key=lambda a: a.start)
    last = max(anchors, key=lambda a: a.end)
    return first, last


@dataclass(frozen=True)
class _Leg:
    node_id: str
    title: str
    depart: datetime
    arrive: datetime | None
    from_loc: tuple[float, float] | None
    to_loc: tuple[float, float] | None


def _classify_lone(
    leg: _Leg, base: tuple[float, float] | None
) -> tuple[_Leg | None, _Leg | None]:
    """Decide whether a single flight is the outbound, the return, or neither.

    Returns ``(outbound, inbound)`` with at most one set. Uses direction versus
    the trip base: arriving from far = the way in; departing to somewhere far =
    the way home; both endpoints near base = an internal hop we don't guard.
    """
    if base is None:
        return None, None
    from_far = leg.from_loc is not None and _haversine_km(leg.from_loc, base) > _BOOKEND_FAR_KM
    to_far = leg.to_loc is not None and _haversine_km(leg.to_loc, base) > _BOOKEND_FAR_KM
    if from_far and not to_far:
        return leg, None  # comes from far, lands near base → outbound
    if to_far and not from_far:
        return None, leg  # leaves base for somewhere far → return
    return None, None  # both near (internal hop) or both far (not our trip)


def flight_conflicts(nodes: list[dict]) -> list[FlightConflict]:
    """Feasibility conflicts between the plan's flights and its dated commitments.

    The **outbound** (way in) must land before the first dated commitment begins;
    the **return** (way home) must depart after the last one ends. Round trips and
    multi-city bookends are read by extremal timing (earliest arrival in, latest
    departure out); a lone flight is placed by direction versus the trip base.
    Returns ``block`` conflicts for physically impossible legs and ``warn`` for
    tight-but-possible ones.
    """
    first, last = _anchor_bounds(nodes)
    if first is None or last is None:
        return []

    # A flight's own timezone makes departure-vs-arrival ordering unreliable
    # across zones (a Detroit 10:03 takeoff is already 17:03 in Greece), so
    # never classify a leg by comparing its *departure instant* to the plan.
    flights: list[_Leg] = []
    for node in nodes:
        if node.get("type") != "flight":
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        meta = node.get("metadata") or {}
        depart = _parse(meta.get("depart_at")) or _parse(node.get("starts_at"))
        if depart is None:
            continue
        flights.append(
            _Leg(
                node_id=node_id,
                title=node.get("title") or "flight",
                depart=depart,
                arrive=_parse(meta.get("arrive_at")),
                from_loc=_coords(meta.get("from_location")),
                to_loc=_coords(meta.get("to_location")),
            )
        )
    if not flights:
        return []

    if len(flights) >= 2:
        # Round trip / multi-city bookends: the way IN is the earliest-arriving
        # leg, the way HOME the latest-departing one. Internal hops sit between
        # both extremes and are never selected.
        with_arrival = [f for f in flights if f.arrive is not None]
        outbound = min(with_arrival, key=lambda f: f.arrive) if with_arrival else None
        inbound: _Leg | None = max(flights, key=lambda f: f.depart)
    else:
        # A single flight can't be placed by timing alone — a late outbound looks
        # "interior" precisely because of the bug we're catching. Direction
        # relative to the trip base is the reliable signal: coming from far = the
        # way in, going far = the way home, neither = an internal hop (skip).
        outbound, inbound = _classify_lone(flights[0], _base_location(nodes))

    conflicts: list[FlightConflict] = []
    if outbound is not None:
        node_id, title, arrive = outbound.node_id, outbound.title, outbound.arrive
        if arrive is not None and arrive >= first.start:
            conflicts.append(
                FlightConflict(
                    node_id,
                    "outbound",
                    "block",
                    f"Outbound {title} arrives {_fmt(arrive)} — at or after the first "
                    f"scheduled item '{first.node.get('title')}' begins "
                    f"({_fmt(first.start)}). The traveler would still be in transit when "
                    f"the plan says they're there. Pick an earlier flight (it likely "
                    f"needs to depart a day sooner).",
                )
            )
        elif arrive is not None and first.start - arrive < timedelta(minutes=_ARRIVAL_MARGIN_MIN):
            margin = int((first.start - arrive).total_seconds() // 60)
            conflicts.append(
                FlightConflict(
                    node_id,
                    "outbound",
                    "warn",
                    f"Outbound {title} arrives {_fmt(arrive)}, only {margin} min before "
                    f"'{first.node.get('title')}' at {_fmt(first.start)} — tight once "
                    f"immigration, bags, and the transfer are counted.",
                )
            )

    if inbound is not None:
        node_id, title, depart = inbound.node_id, inbound.title, inbound.depart
        if depart <= last.end:
            conflicts.append(
                FlightConflict(
                    node_id,
                    "return",
                    "block",
                    f"Return {title} departs {_fmt(depart)} — at or before the last "
                    f"scheduled item '{last.node.get('title')}' ends ({_fmt(last.end)}). "
                    f"The traveler can't make the gate. Pick a later departure.",
                )
            )
        elif depart - last.end < timedelta(minutes=_DEPARTURE_MARGIN_MIN):
            margin = int((depart - last.end).total_seconds() // 60)
            conflicts.append(
                FlightConflict(
                    node_id,
                    "return",
                    "warn",
                    f"Return {title} departs {_fmt(depart)}, only {margin} min after "
                    f"'{last.node.get('title')}' ends ({_fmt(last.end)}) — tight once the "
                    f"airport transfer, check-in, and security are counted.",
                )
            )

    return conflicts
