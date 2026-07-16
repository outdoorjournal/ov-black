"""Column values ↔ kernel schedules.

The bridge between the nodes table's canonical schedule columns (0055) and the
kernel's ``Schedule`` values. Pure — takes and returns plain scalars, so it is
usable from ORM rows, raw SQL results, and tests alike. The shape rules here
mirror the ``nodes_schedule_*`` CHECK constraints: a combination the database
would reject is a ``KernelViolation`` here.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from app.kernel.errors import KernelViolation
from app.kernel.schedule import (
    AbsoluteStamp,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    Schedule,
)

_KIND_RELATIVE = "relative"
_KIND_PINNED = "pinned"


def schedule_from_columns(
    *,
    schedule_kind: str | None,
    start_day_offset: int | None,
    start_date: date | None,
    start_wall_time: time | None,
    start_tz: str | None,
    end_day_offset: int | None = None,
    end_date: date | None = None,
    end_wall_time: time | None = None,
    end_tz: str | None = None,
) -> Schedule | None:
    if schedule_kind is None:
        if start_wall_time is not None or start_day_offset is not None or start_date is not None:
            raise KernelViolation(
                "malformed_schedule_row", "schedule fields present without a schedule_kind"
            )
        return None

    if start_wall_time is None or start_tz is None:
        raise KernelViolation(
            "malformed_schedule_row", f"{schedule_kind} row is missing start_wall_time/start_tz"
        )
    has_end = end_wall_time is not None
    if has_end and end_tz is None:
        raise KernelViolation("malformed_schedule_row", "end_wall_time present without end_tz")

    if schedule_kind == _KIND_RELATIVE:
        if start_day_offset is None or start_date is not None:
            raise KernelViolation(
                "malformed_schedule_row", "relative row must carry day offsets, not dates"
            )
        end_rel: RelativeStamp | None = None
        if has_end:
            if end_day_offset is None or end_date is not None:
                raise KernelViolation(
                    "malformed_schedule_row", "relative end must carry a day offset, not a date"
                )
            assert end_wall_time is not None and end_tz is not None
            end_rel = RelativeStamp(
                day_offset=end_day_offset, wall_time=end_wall_time, tz_name=end_tz
            )
        return RelativeSchedule(
            start=RelativeStamp(
                day_offset=start_day_offset, wall_time=start_wall_time, tz_name=start_tz
            ),
            end=end_rel,
        )

    if schedule_kind == _KIND_PINNED:
        if start_date is None or start_day_offset is not None:
            raise KernelViolation(
                "malformed_schedule_row", "pinned row must carry dates, not day offsets"
            )
        end_abs: AbsoluteStamp | None = None
        if has_end:
            if end_date is None or end_day_offset is not None:
                raise KernelViolation(
                    "malformed_schedule_row", "pinned end must carry a date, not a day offset"
                )
            assert end_wall_time is not None and end_tz is not None
            end_abs = AbsoluteStamp(on=end_date, wall_time=end_wall_time, tz_name=end_tz)
        return PinnedSchedule(
            start=AbsoluteStamp(on=start_date, wall_time=start_wall_time, tz_name=start_tz),
            end=end_abs,
        )

    raise KernelViolation("malformed_schedule_row", f"unknown schedule_kind {schedule_kind!r}")


def columns_from_schedule(schedule: Schedule | None) -> dict[str, Any]:
    """The full column dict for a schedule — always all ten keys, so callers
    that splat it into an UPDATE clear stale fields on kind changes."""
    columns: dict[str, Any] = {
        "schedule_kind": None,
        "start_day_offset": None,
        "start_date": None,
        "start_wall_time": None,
        "start_tz": None,
        "end_day_offset": None,
        "end_date": None,
        "end_wall_time": None,
        "end_tz": None,
    }
    if schedule is None:
        return columns
    if isinstance(schedule, RelativeSchedule):
        columns["schedule_kind"] = _KIND_RELATIVE
        columns["start_day_offset"] = schedule.start.day_offset
        if schedule.end is not None:
            columns["end_day_offset"] = schedule.end.day_offset
    else:
        columns["schedule_kind"] = _KIND_PINNED
        columns["start_date"] = schedule.start.on
        if schedule.end is not None:
            columns["end_date"] = schedule.end.on
    columns["start_wall_time"] = schedule.start.wall_time
    columns["start_tz"] = schedule.start.tz_name
    if schedule.end is not None:
        columns["end_wall_time"] = schedule.end.wall_time
        columns["end_tz"] = schedule.end.tz_name
    return columns
