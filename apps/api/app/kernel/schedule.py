"""The kernel time model: wall-clock canonical, absolute derived.

A schedule stores what was promised to a human — "9am, Europe/Athens" — and the
absolute instant is *derived* through the tzdb at read time. The itinerary's
``anchor_date`` (Day 1's calendar date) is the only place a relative schedule
touches the calendar, so re-dating a trip is a one-field change that cannot
corrupt per-node data. See doc/itin-time.md.

Two schedule shapes:

* ``RelativeSchedule`` — anchored to a trip day (``day_offset`` from Day 1,
  which is offset 0; negative offsets are legal — an outbound flight may leave
  home the day before Day 1). Moves when the anchor moves.
* ``PinnedSchedule`` — anchored to the world (calendar dates). Never moves when
  the anchor moves. Booking pins; cancelling un-pins; advisors may pin
  fixed-date events explicitly.

Both shapes carry per-endpoint IANA zones, so a flight departing Detroit and
landing in Athens holds each endpoint in its own zone and cross-zone ordering
falls out of resolution rather than string comparison.

DST policy (deliberate, tested): resolution uses PEP 495 ``fold=0`` semantics —
a nonexistent wall time (spring-forward gap) rolls forward by the width of the
gap; an ambiguous wall time (fall-back fold) takes its first occurrence. A 9am
tour is 9am in August and 9am in December; only the derived instant differs.

End times derive by *wall-clock* addition (19:00 + 120min = 21:00 on the wall,
whatever the zone did in between): durations here are promises about the local
clock, not elapsed physics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.kernel.errors import KernelViolation


def _require_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise KernelViolation("invalid_zone", f"{tz_name!r} is not an IANA timezone name") from exc


def _require_wall(wall_time: time) -> None:
    if wall_time.tzinfo is not None:
        raise KernelViolation(
            "aware_wall_time",
            "wall_time must be naive — the zone lives in tz_name, not on the time",
        )


@dataclass(frozen=True)
class RelativeStamp:
    """A wall-clock promise tied to a trip day, not a calendar date."""

    day_offset: int  # Day N of the trip ≡ offset N-1; negative = before Day 1
    wall_time: time
    tz_name: str

    def __post_init__(self) -> None:
        _require_zone(self.tz_name)
        _require_wall(self.wall_time)


@dataclass(frozen=True)
class AbsoluteStamp:
    """A wall-clock promise tied to a calendar date in a zone."""

    on: date
    wall_time: time
    tz_name: str

    def __post_init__(self) -> None:
        _require_zone(self.tz_name)
        _require_wall(self.wall_time)


@dataclass(frozen=True)
class RelativeSchedule:
    """Anchor-relative: moves when the trip's anchor date moves."""

    start: RelativeStamp
    end: RelativeStamp | None = None


@dataclass(frozen=True)
class PinnedSchedule:
    """World-pinned: holds its calendar dates regardless of the anchor."""

    start: AbsoluteStamp
    end: AbsoluteStamp | None = None


Schedule = RelativeSchedule | PinnedSchedule


@dataclass(frozen=True)
class ResolvedSpan:
    """A schedule projected onto the timeline: aware instants."""

    start: datetime
    end: datetime | None


def resolve_wall(on: date, wall_time: time, tz_name: str) -> datetime:
    """One wall-clock promise → one aware instant, under the DST policy above."""
    return datetime.combine(on, wall_time.replace(fold=0), tzinfo=_require_zone(tz_name))


def resolve_stamp(stamp: RelativeStamp | AbsoluteStamp, anchor: date | None) -> datetime | None:
    """A stamp → an instant; ``None`` for a relative stamp on an undated trip."""
    if isinstance(stamp, AbsoluteStamp):
        return resolve_wall(stamp.on, stamp.wall_time, stamp.tz_name)
    if anchor is None:
        return None
    return resolve_wall(anchor + timedelta(days=stamp.day_offset), stamp.wall_time, stamp.tz_name)


def resolve_schedule(schedule: Schedule, anchor: date | None) -> ResolvedSpan | None:
    """A schedule → a span of instants; ``None`` when it cannot resolve yet."""
    start = resolve_stamp(schedule.start, anchor)
    if start is None:
        return None
    end = resolve_stamp(schedule.end, anchor) if schedule.end is not None else None
    return ResolvedSpan(start=start, end=end)


def pin_schedule(schedule: RelativeSchedule, anchor: date) -> PinnedSchedule:
    """Promote day-offsets to the calendar dates the anchor currently implies."""

    def _pin(stamp: RelativeStamp) -> AbsoluteStamp:
        return AbsoluteStamp(
            on=anchor + timedelta(days=stamp.day_offset),
            wall_time=stamp.wall_time,
            tz_name=stamp.tz_name,
        )

    return PinnedSchedule(
        start=_pin(schedule.start),
        end=_pin(schedule.end) if schedule.end is not None else None,
    )


def unpin_schedule(schedule: PinnedSchedule, anchor: date) -> RelativeSchedule:
    """Demote calendar dates back to day-offsets against the given anchor."""

    def _unpin(stamp: AbsoluteStamp) -> RelativeStamp:
        return RelativeStamp(
            day_offset=(stamp.on - anchor).days,
            wall_time=stamp.wall_time,
            tz_name=stamp.tz_name,
        )

    return RelativeSchedule(
        start=_unpin(schedule.start),
        end=_unpin(schedule.end) if schedule.end is not None else None,
    )


_WALL_EPOCH = date(2000, 1, 1)  # any date works: only used for wall arithmetic


def relative(
    day: int,
    wall_time: time,
    tz_name: str,
    *,
    duration_minutes: int | None = None,
    end: RelativeStamp | None = None,
) -> RelativeSchedule:
    """Convenience constructor; ``duration_minutes`` adds on the wall clock.

    ``day`` is the human Day N label (Day 1 = offset 0). A duration crossing
    midnight rolls the end stamp onto the next day offset.
    """
    if duration_minutes is not None and end is not None:
        raise KernelViolation("over_specified_end", "pass duration_minutes or end, not both")
    start = RelativeStamp(day_offset=day - 1, wall_time=wall_time, tz_name=tz_name)
    if duration_minutes is not None:
        base = datetime.combine(_WALL_EPOCH, wall_time)
        rolled = base + timedelta(minutes=duration_minutes)
        end = RelativeStamp(
            day_offset=start.day_offset + (rolled.date() - _WALL_EPOCH).days,
            wall_time=rolled.time(),
            tz_name=tz_name,
        )
    return RelativeSchedule(start=start, end=end)


def day_index(schedule: Schedule, anchor: date | None) -> int | None:
    """The human Day N label for a schedule, or ``None`` if underivable.

    Relative schedules know their day by construction; pinned schedules derive
    it from the anchor (a pinned node on an undated trip has no day label —
    it has a calendar date instead).
    """
    if isinstance(schedule, RelativeSchedule):
        return schedule.start.day_offset + 1
    if anchor is None:
        return None
    return (schedule.start.on - anchor).days + 1


@dataclass(frozen=True)
class ResolvedStampView:
    """One schedule endpoint projected for display (Phase 4 read shape).

    Everything a renderer needs without doing time math: the human Day N
    label, the local calendar date, the wall clock, the zone, and the resolved
    absolute instant. ``day_index`` is None for a pinned stamp on an undated
    trip (it has a date instead); ``on``/``instant`` are None for a relative
    stamp on an undated trip (it has a day label instead).
    """

    day_index: int | None
    on: date | None
    wall_time: time
    tz_name: str
    instant: datetime | None


@dataclass(frozen=True)
class ResolvedScheduleView:
    """A whole schedule projected for display: per-endpoint local views plus
    the day span (calendar days covered — 2+ for overnight/multi-day items,
    including a red-eye whose endpoints land on different local dates)."""

    kind: str  # "relative" | "pinned"
    start: ResolvedStampView
    end: ResolvedStampView | None
    day_span: int


def _view_stamp(stamp: RelativeStamp | AbsoluteStamp, anchor: date | None) -> ResolvedStampView:
    if isinstance(stamp, RelativeStamp):
        return ResolvedStampView(
            day_index=stamp.day_offset + 1,
            on=anchor + timedelta(days=stamp.day_offset) if anchor is not None else None,
            wall_time=stamp.wall_time,
            tz_name=stamp.tz_name,
            instant=resolve_stamp(stamp, anchor),
        )
    return ResolvedStampView(
        day_index=(stamp.on - anchor).days + 1 if anchor is not None else None,
        on=stamp.on,
        wall_time=stamp.wall_time,
        tz_name=stamp.tz_name,
        instant=resolve_stamp(stamp, anchor),
    )


def resolve_view(schedule: Schedule, anchor: date | None) -> ResolvedScheduleView:
    """Project a schedule into its display view against the given anchor."""
    start = _view_stamp(schedule.start, anchor)
    end = _view_stamp(schedule.end, anchor) if schedule.end is not None else None
    if isinstance(schedule, RelativeSchedule):
        end_offset = schedule.end.day_offset if schedule.end is not None else None
        day_span = end_offset - schedule.start.day_offset + 1 if end_offset is not None else 1
        kind = "relative"
    else:
        day_span = (schedule.end.on - schedule.start.on).days + 1 if schedule.end is not None else 1
        kind = "pinned"
    return ResolvedScheduleView(kind=kind, start=start, end=end, day_span=max(1, day_span))
