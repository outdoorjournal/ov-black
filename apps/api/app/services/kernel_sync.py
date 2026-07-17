"""Keep the canonical kernel-schedule columns in sync with legacy writes.

Phase 3 transitional glue (doc/itin-time.md): the API's write contract is still
ISO-with-offset (``starts_at`` + the mirrored ``metadata.start_time`` /
``tz_offset_minutes``), so every schedule-touching write derives the node's
canonical columns here — the Python twin of the 0055
``kernel_backfill_schedule()`` SQL function, same rules:

* committed (booked/confirmed) nodes and nodes on anchorless itineraries pin
  to their calendar dates; everything else is anchor-relative;
* zones are ``Etc/GMT±N`` pseudo-zones derived from the stored offset —
  instant-exact but DST-blind — until the API accepts real IANA zones.

Retime consumes these columns in the other direction: a node's anchor-relative
schedule is resolved against the NEW anchor to produce its new ``starts_at``,
which is what makes retime a derivation instead of a parse-shift-rewrite loop.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.kernel import (
    AbsoluteStamp,
    KernelViolation,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    Schedule,
    columns_from_schedule,
    schedule_from_columns,
    unpin_schedule,
)
from app.models.itinerary import Node, NodeStatus, NodeType

_COMMITTED = (NodeStatus.booked, NodeStatus.confirmed)

# Etc/GMT pseudo-zones exist for whole hours in [-12h, +14h]; note the inverted
# POSIX sign (Etc/GMT-3 == UTC+3).
_PSEUDO_MIN = -720
_PSEUDO_MAX = 840


def pseudo_zone(offset_minutes: int) -> str | None:
    if offset_minutes % 60 or not (_PSEUDO_MIN <= offset_minutes <= _PSEUDO_MAX):
        return None
    hours = offset_minutes // 60
    if hours == 0:
        return "Etc/GMT"
    return f"Etc/GMT{'-' if hours > 0 else '+'}{abs(hours)}"


def is_date_sensitive(node: Node) -> bool:
    """Whether this node's content snapshot was quoted for a specific date, so
    a schedule move stales it (doc/itin-time.md "Moves can invalidate
    content"). Flights with provider provenance for now; the revalidation-scope
    open decision may widen this."""
    return node.type is NodeType.flight and node.source is not None


def _offset_minutes(metadata: Any) -> int:
    if isinstance(metadata, dict):
        raw = metadata.get("tz_offset_minutes")
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
    return 0


def _bounds(node: Node) -> tuple[datetime | None, datetime | None]:
    lower = getattr(node.starts_at, "lower", None)
    upper = getattr(node.starts_at, "upper", None)
    return (
        lower if isinstance(lower, datetime) else None,
        upper if isinstance(upper, datetime) else None,
    )


def derive_schedule(node: Node, anchor_date: date | None) -> Schedule | None:
    """The node's canonical schedule, derived from its legacy representation.

    ``None`` when the node is unscheduled — or when its offset has no
    pseudo-zone (non-whole-hour; unseen in practice), in which case the
    canonical columns are left for manual review rather than written wrong.
    """
    lower, upper = _bounds(node)
    if lower is None:
        return None
    zone = pseudo_zone(_offset_minutes(node.metadata_))
    if zone is None:
        return None
    tz = ZoneInfo(zone)
    s_local = lower.astimezone(tz)
    e_local = upper.astimezone(tz) if upper is not None else None

    if node.status in _COMMITTED or anchor_date is None:
        return PinnedSchedule(
            start=AbsoluteStamp(on=s_local.date(), wall_time=s_local.time(), tz_name=zone),
            end=(
                AbsoluteStamp(on=e_local.date(), wall_time=e_local.time(), tz_name=zone)
                if e_local is not None
                else None
            ),
        )
    return RelativeSchedule(
        start=RelativeStamp(
            day_offset=(s_local.date() - anchor_date).days,
            wall_time=s_local.time(),
            tz_name=zone,
        ),
        end=(
            RelativeStamp(
                day_offset=(e_local.date() - anchor_date).days,
                wall_time=e_local.time(),
                tz_name=zone,
            )
            if e_local is not None
            else None
        ),
    )


def sync_node_schedule(node: Node, anchor_date: date | None) -> None:
    """Recompute and write the node's canonical columns from its legacy
    representation. Idempotent; call after any write that may have touched
    ``starts_at``, the metadata mirrors, or a committed-status boundary."""
    schedule = derive_schedule(node, anchor_date)
    if schedule is None and node.starts_at is not None and node.schedule_kind is not None:
        return  # no pseudo-zone for this offset — keep the existing columns
    apply_schedule_columns(node, schedule)


def apply_schedule_columns(node: Node, schedule: Schedule | None) -> None:
    for column, value in columns_from_schedule(schedule).items():
        setattr(node, column, value)


def decoded_schedule(node: Node) -> Schedule | None:
    """The node's canonical schedule as stored, or ``None`` when absent or
    malformed (malformed rows self-heal on the next sync)."""
    try:
        return schedule_from_columns(
            schedule_kind=node.schedule_kind,
            start_day_offset=node.start_day_offset,
            start_date=node.start_date,
            start_wall_time=node.start_wall_time,
            start_tz=node.start_tz,
            end_day_offset=node.end_day_offset,
            end_date=node.end_date,
            end_wall_time=node.end_wall_time,
            end_tz=node.end_tz,
        )
    except KernelViolation:
        return None


def relative_schedule_of(node: Node, fallback_anchor: date) -> RelativeSchedule | None:
    """The node's schedule as anchor-relative — what a retime moves.

    Canonical relative rows are taken as stored. Canonical pinned rows on an
    UNCOMMITTED node (backfilled anchorless trips, healed advisor pins) unpin
    against ``fallback_anchor`` — exactly the legacy shift-by-delta semantics.
    Rows with no usable canonical derive from the legacy columns. Committed
    nodes are the caller's job to hold, not this function's.
    """
    decoded = decoded_schedule(node)
    if isinstance(decoded, RelativeSchedule):
        return decoded
    if isinstance(decoded, PinnedSchedule):
        return unpin_schedule(decoded, fallback_anchor)
    derived = derive_schedule(node, fallback_anchor)
    return derived if isinstance(derived, RelativeSchedule) else None
