"""Nightly lodging presence: where the traveler sleeps, derived on read.

A lodging stay is presence, not an event. The only timeline moments a stay
owns are check-in and checkout; the nights between are a fact about where the
traveler is based, so they are derived from span coverage — never stored (the
same discipline as display buckets and resolved schedule views). Coverage runs
[check-in night, checkout morning): the checkout day is not a night, and a
stay with no known checkout covers through the last night the trip knows
about. When two stays cover the same night (a same-day hotel change, an
overnight excursion away from a kept room), the later check-in wins —
presence follows the newest room key, while the paid-for room stays visible
on its own node.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.kernel.graph import Graph, Node
from app.kernel.schedule import AbsoluteStamp, RelativeStamp, resolve_schedule
from app.models.itinerary import NodeStatus, NodeType

# Types that put a roof over a night. A set rather than an inline hotel check
# so a future lodging kind (villa, chalet, yacht cabin) joins presence — and
# leaves event-overlap analysis — by joining this set.
LODGING_TYPES: frozenset[NodeType] = frozenset({NodeType.hotel})


@dataclass(frozen=True)
class NightLodging:
    """One night's roof: the evening of Day ``day_index`` is spent at ``node_id``."""

    day_index: int  # human Day N label of the night's evening
    on: date | None  # calendar date of that evening; None while the trip is undated
    node_id: str


def _offset(stamp: RelativeStamp | AbsoluteStamp, anchor: date | None) -> int | None:
    """A stamp's day offset from Day 1, or None when underivable (a pinned
    stamp on an undated trip has a calendar date but no day label yet)."""
    if isinstance(stamp, RelativeStamp):
        return stamp.day_offset
    if anchor is None:
        return None
    return (stamp.on - anchor).days


def _is_live_lodging(node: Node) -> bool:
    return (
        node.type in LODGING_TYPES
        and node.schedule is not None
        and node.status is not NodeStatus.discarded
    )


def _trip_last_offset(graph: Graph, anchor: date | None) -> int | None:
    """The latest day offset any scheduled node touches — the bound an
    open-ended stay covers through."""
    last: int | None = None
    for node in graph.nodes.values():
        if node.schedule is None or node.status is NodeStatus.discarded:
            continue
        for stamp in (node.schedule.start, node.schedule.end):
            if stamp is None:
                continue
            off = _offset(stamp, anchor)
            if off is not None and (last is None or off > last):
                last = off
    return last


def nightly_lodging(graph: Graph) -> tuple[NightLodging, ...]:
    """Every covered trip night → the lodging node whose stay owns it.

    Works symbolically on day offsets, so an undated trip still gets Day N
    labels from its relative stays (a pinned stay on an undated trip is
    skipped — it has no day label yet, matching ``resolve_view``). Nights the
    plan leaves roofless simply don't appear. Ordered by night.
    """
    anchor = graph.anchor_date
    last_offset = _trip_last_offset(graph, anchor)
    stays: list[tuple[int, time, str, int]] = []  # (start_off, checkin_wall, id, end_off_excl)
    for node in graph.nodes.values():
        if not _is_live_lodging(node):
            continue
        assert node.schedule is not None  # _is_live_lodging
        start_off = _offset(node.schedule.start, anchor)
        if start_off is None:
            continue
        end_stamp = node.schedule.end
        if end_stamp is not None:
            end_off = _offset(end_stamp, anchor)
            if end_off is None or end_off <= start_off:
                continue  # a day-use room covers no night
        else:
            # Open-ended stay: cover through the trip's last known night. The
            # stay's own start participates in the extent, so this is always
            # at least the check-in night.
            end_off = (last_offset if last_offset is not None else start_off) + 1
        stays.append((start_off, node.schedule.start.wall_time, node.id, end_off))

    # Ascending by check-in, so a later check-in overwrites: the newest room
    # key owns the night.
    stays.sort(key=lambda s: (s[0], s[1]))
    nights: dict[int, str] = {}
    for start_off, _wall, node_id, end_off in stays:
        for off in range(start_off, end_off):
            nights[off] = node_id
    return tuple(
        NightLodging(
            day_index=off + 1,
            on=anchor + timedelta(days=off) if anchor is not None else None,
            node_id=nights[off],
        )
        for off in sorted(nights)
    )


def lodging_at(graph: Graph, instant: datetime) -> Node | None:
    """The lodging whose stay covers ``instant`` (aware) — the traveler's base
    at that moment.

    Valid only from check-in forward: before the check-in instant the
    traveler has a room *tonight* but is not based anywhere yet, so "you're
    near your hotel" is only ever true past the first check-in. Returns None
    on an undated trip (relative stays can't resolve to instants) and after
    checkout. Ties (an excursion night inside a kept room's span) go to the
    latest check-in.
    """
    best: tuple[datetime, Node] | None = None
    for node in graph.nodes.values():
        if not _is_live_lodging(node):
            continue
        assert node.schedule is not None  # _is_live_lodging
        span = resolve_schedule(node.schedule, graph.anchor_date)
        if span is None or instant < span.start:
            continue
        if span.end is not None and instant >= span.end:
            continue
        if best is None or span.start >= best[0]:
            best = (span.start, node)
    return best[1] if best is not None else None
