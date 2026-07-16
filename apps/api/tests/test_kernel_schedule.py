"""Kernel time model: wall-clock canonical, DST policy, pin/unpin round-trips.

The load-bearing property throughout: a wall-clock promise ("9am, Athens")
never moves; only the derived instant does. See doc/itin-time.md.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.kernel import (
    AbsoluteStamp,
    KernelViolation,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    day_index,
    pin_schedule,
    relative,
    resolve_schedule,
    resolve_wall,
    unpin_schedule,
)

ATHENS = "Europe/Athens"
NEW_YORK = "America/New_York"


class TestResolveWall:
    def test_wall_clock_survives_dst_seasons(self):
        """A 9am Athens tour is 9am in August (+3) and 9am in December (+2):
        the derived instant moves, the promise does not."""
        summer = resolve_wall(date(2026, 8, 7), time(9, 0), ATHENS)
        winter = resolve_wall(date(2026, 12, 7), time(9, 0), ATHENS)
        assert (summer.hour, summer.minute) == (9, 0)
        assert (winter.hour, winter.minute) == (9, 0)
        assert summer.utcoffset() == timedelta(hours=3)
        assert winter.utcoffset() == timedelta(hours=2)
        assert summer.astimezone(UTC).hour == 6
        assert winter.astimezone(UTC).hour == 7

    def test_spring_forward_gap_rolls_forward(self):
        """2:30am on the US spring-forward day does not exist; the resolved
        instant lands at 3:30 EDT (rolled forward by the width of the gap)."""
        resolved = resolve_wall(date(2026, 3, 8), time(2, 30), NEW_YORK)
        on_the_ground = resolved.astimezone(UTC).astimezone(resolved.tzinfo)
        assert (on_the_ground.hour, on_the_ground.minute) == (3, 30)

    def test_fall_back_fold_takes_first_occurrence(self):
        """1:30am on the US fall-back day happens twice; policy is the first
        occurrence (still on daylight time, -4)."""
        resolved = resolve_wall(date(2026, 11, 1), time(1, 30), NEW_YORK)
        assert resolved.utcoffset() == timedelta(hours=-4)

    def test_invalid_zone_is_a_violation(self):
        with pytest.raises(KernelViolation) as exc:
            resolve_wall(date(2026, 8, 7), time(9, 0), "Mars/Olympus_Mons")
        assert exc.value.code == "invalid_zone"

    def test_offset_style_zone_is_a_violation(self):
        """Fixed offsets are cached answers that go stale; only named zones."""
        with pytest.raises(KernelViolation):
            RelativeStamp(day_offset=0, wall_time=time(9, 0), tz_name="+03:00")


class TestResolveSchedule:
    def test_relative_on_undated_trip_does_not_resolve(self):
        schedule = relative(4, time(9, 0), ATHENS)
        assert resolve_schedule(schedule, None) is None

    def test_relative_resolves_against_anchor(self):
        """Day 4 at 9am with anchor Aug 1 = Aug 4 at 9am — the doc's example."""
        schedule = relative(4, time(9, 0), ATHENS)
        span = resolve_schedule(schedule, date(2026, 8, 1))
        assert span is not None
        assert span.start == datetime(2026, 8, 4, 9, 0, tzinfo=span.start.tzinfo)
        assert span.start.astimezone(UTC) == datetime(2026, 8, 4, 6, 0, tzinfo=UTC)

    def test_pinned_ignores_anchor(self):
        schedule = PinnedSchedule(start=AbsoluteStamp(date(2026, 8, 14), time(10, 3), NEW_YORK))
        with_anchor = resolve_schedule(schedule, date(2026, 8, 1))
        without = resolve_schedule(schedule, None)
        assert with_anchor == without
        assert with_anchor is not None

    def test_cross_zone_endpoints_order_correctly(self):
        """Detroit 10:03 departure vs Athens 15:00 same-day item: the takeoff
        is already 17:03 in Greece — resolution must order it after."""
        depart = resolve_wall(date(2026, 8, 14), time(10, 3), "America/Detroit")
        item = resolve_wall(date(2026, 8, 14), time(15, 0), ATHENS)
        assert depart > item

    def test_negative_day_offset_is_legal(self):
        """The outbound may leave home the day before Day 1."""
        schedule = RelativeSchedule(
            start=RelativeStamp(day_offset=-1, wall_time=time(18, 0), tz_name=NEW_YORK)
        )
        span = resolve_schedule(schedule, date(2026, 8, 1))
        assert span is not None
        assert span.start.date() == date(2026, 7, 31)


class TestPinUnpin:
    def test_round_trip_is_identity(self):
        anchor = date(2026, 8, 1)
        original = relative(4, time(9, 0), ATHENS, duration_minutes=120)
        assert unpin_schedule(pin_schedule(original, anchor), anchor) == original

    def test_pin_maps_day_offsets_to_dates(self):
        pinned = pin_schedule(relative(4, time(9, 0), ATHENS), date(2026, 8, 1))
        assert pinned.start.on == date(2026, 8, 4)

    def test_unpin_against_a_moved_anchor_changes_the_day(self):
        """Re-derive Day N against a different anchor: the calendar date holds
        (world-pinned), the day label moves."""
        pinned = PinnedSchedule(start=AbsoluteStamp(date(2026, 8, 4), time(9, 0), ATHENS))
        assert unpin_schedule(pinned, date(2026, 8, 2)).start.day_offset == 2


class TestRelativeConstructor:
    def test_duration_crossing_midnight_rolls_the_day(self):
        schedule = relative(2, time(23, 0), ATHENS, duration_minutes=180)
        assert schedule.end is not None
        assert schedule.end.day_offset == 2  # Day 3
        assert schedule.end.wall_time == time(2, 0)

    def test_duration_and_end_together_is_a_violation(self):
        end = RelativeStamp(day_offset=1, wall_time=time(11, 0), tz_name=ATHENS)
        with pytest.raises(KernelViolation):
            relative(1, time(9, 0), ATHENS, duration_minutes=60, end=end)


class TestDayIndex:
    def test_relative_knows_its_day_without_an_anchor(self):
        assert day_index(relative(4, time(9, 0), ATHENS), None) == 4

    def test_pinned_derives_its_day_from_the_anchor(self):
        pinned = PinnedSchedule(start=AbsoluteStamp(date(2026, 8, 7), time(9, 0), ATHENS))
        assert day_index(pinned, date(2026, 8, 1)) == 7
        assert day_index(pinned, None) is None
