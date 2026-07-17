"""Kernel-computed provisional placement for unscheduled nodes.

Phase 4 of doc/itin-time.md: the web adapter used to synthesize a layout slot
for every undated card (9:00 + 60-minute steps on Day 1) so the timeline could
render it. That synthesis is now a kernel computation the read path serializes
— one implementation of the rule, marked ``synthesized`` so no consumer ever
mistakes a provisional slot for a real placement.

Pure: plain ids and zone names in, ``RelativeSchedule`` values out.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import time

from app.kernel.schedule import RelativeSchedule, relative

DEFAULT_ZONE = "UTC"

# Synthesis rule (mirrors the retired web-adapter constants): the first
# undated card lands at 9:00 on Day 1, the rest follow at 60-minute steps,
# rolling onto later days past midnight.
_SYNTH_START_MINUTE = 9 * 60
_SYNTH_STEP_MINUTES = 60
_MINUTES_PER_DAY = 24 * 60


def trip_default_zone(zones: Iterable[str | None]) -> str:
    """The trip's working zone: the most common zone among scheduled nodes.

    Deterministic on ties (alphabetical order wins), ``UTC`` when nothing is
    scheduled yet. This replaces the web's offset-tallying heuristic — same
    idea, but computed once from canonical zones instead of guessed from
    metadata strings.
    """
    counts = Counter(z for z in zones if z)
    if not counts:
        return DEFAULT_ZONE
    return max(sorted(counts), key=lambda z: counts[z])


def follows_order(ids: Sequence[str], edges: Iterable[tuple[str, str]]) -> list[str]:
    """Order ``ids`` by ``follows`` chains where possible, else input order.

    Chains start from ids with no incoming edge (in input order) and walk
    forward; anything unreachable (cycles, orphans) appends in input order.
    Edges touching ids outside the set are ignored.
    """
    id_set = set(ids)
    next_of: dict[str, str] = {}
    has_incoming: set[str] = set()
    for from_id, to_id in edges:
        if from_id not in id_set or to_id not in id_set:
            continue
        next_of[from_id] = to_id
        has_incoming.add(to_id)

    ordered: list[str] = []
    seen: set[str] = set()
    for start in ids:
        if start in has_incoming:
            continue
        cur: str | None = start
        while cur is not None and cur not in seen:
            ordered.append(cur)
            seen.add(cur)
            cur = next_of.get(cur)
    for node_id in ids:
        if node_id not in seen:
            ordered.append(node_id)
    return ordered


def synthesize_placements(node_ids: Sequence[str], tz_name: str) -> dict[str, RelativeSchedule]:
    """Provisional Day-1 slots for unscheduled nodes, in the given order."""
    placements: dict[str, RelativeSchedule] = {}
    for i, node_id in enumerate(node_ids):
        minute = _SYNTH_START_MINUTE + i * _SYNTH_STEP_MINUTES
        day = 1 + minute // _MINUTES_PER_DAY
        wall = time(hour=(minute % _MINUTES_PER_DAY) // 60, minute=minute % 60)
        placements[node_id] = relative(day, wall, tz_name)
    return placements
