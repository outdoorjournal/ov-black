"""Unit tests for the live Japan build's pure helpers.

The full ``build_live_japan_itinerary`` flow hits live providers + a DB, so it
lives in manual/e2e verification. These cover the pure timing logic that turns
a Duffel offer's card metadata into a node schedule (``_flight_schedule``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.inventory.schemas import FlightItem, MealItem
from app.services.japan_live import _flight_schedule, _pick_flight


def _flight(arriving_local: str, *, source_id: str, tz: str = "Asia/Tokyo") -> FlightItem:
    """A FlightItem whose offer lands at ``arriving_local`` (offset-less) in ``tz``."""
    raw: dict[str, Any] = {
        "slices": [
            {
                "segments": [
                    {
                        "origin": {"iata_code": "LAX", "time_zone": "America/Los_Angeles"},
                        "departing_at": "2026-08-31T11:00:00",
                        "destination": {"iata_code": "HND", "time_zone": tz},
                        "arriving_at": arriving_local,
                    }
                ]
            }
        ]
    }
    return FlightItem(source="duffel", source_id=source_id, title="LAX → HND", raw=raw)


def test_flight_schedule_spans_depart_to_arrive() -> None:
    # Real LAX→HND: departs PDT, arrives JST 12h20m later (across the date line
    # and time zones). Anchor = departure; width = the true instant delta.
    start, duration = _flight_schedule(
        {
            "depart_at": "2026-07-31T23:13:00-07:00",
            "arrive_at": "2026-08-02T03:33:00+09:00",
        }
    )
    assert start == "2026-07-31T23:13:00-07:00"
    assert duration == 740


def test_flight_schedule_missing_arrive_anchors_without_duration() -> None:
    start, duration = _flight_schedule({"depart_at": "2026-07-31T23:13:00-07:00"})
    assert start == "2026-07-31T23:13:00-07:00"
    assert duration is None


def test_flight_schedule_missing_depart_is_unscheduled() -> None:
    assert _flight_schedule({"arrive_at": "2026-08-02T03:33:00+09:00"}) == (None, None)
    assert _flight_schedule({}) == (None, None)


def test_flight_schedule_unparseable_depart_is_unscheduled() -> None:
    assert _flight_schedule({"depart_at": "not-a-datetime"}) == (None, None)


def test_flight_schedule_naive_aware_mismatch_anchors_without_duration() -> None:
    # A tz-naive depart with a tz-aware arrive can't be differenced; keep the
    # anchor, drop the width rather than raise.
    start, duration = _flight_schedule(
        {
            "depart_at": "2026-07-31T23:13:00",
            "arrive_at": "2026-08-02T03:33:00+09:00",
        }
    )
    assert start == "2026-07-31T23:13:00"
    assert duration is None


def test_flight_schedule_nonpositive_duration_dropped() -> None:
    # Arrive not after depart (bad data) → anchor only, no zero/negative bar.
    start, duration = _flight_schedule(
        {
            "depart_at": "2026-07-31T23:13:00-07:00",
            "arrive_at": "2026-07-31T23:13:00-07:00",
        }
    )
    assert start == "2026-07-31T23:13:00-07:00"
    assert duration is None


def test_pick_flight_prefers_earliest_arrival_on_target_day() -> None:
    # Cheapest-first order puts a late connection ahead of a dawn nonstop, and
    # a next-day arrival ahead of both. The pick lands on the target day, as
    # early as possible, so the day's activities follow the touchdown.
    target = date(2026, 9, 1)
    items = [
        _flight("2026-09-02T02:30:00", source_id="next-day-redeye"),
        _flight("2026-09-01T23:30:00", source_id="late-connection"),
        _flight("2026-09-01T04:45:00", source_id="dawn-nonstop"),
    ]
    picked = _pick_flight(items, target)
    assert picked is not None and picked.source_id == "dawn-nonstop"


def test_pick_flight_falls_back_to_first_when_none_land_on_day() -> None:
    target = date(2026, 9, 1)
    items = [
        _flight("2026-09-02T02:30:00", source_id="cheapest-next-day"),
        _flight("2026-09-03T09:00:00", source_id="two-days-out"),
    ]
    picked = _pick_flight(items, target)
    assert picked is not None and picked.source_id == "cheapest-next-day"


def test_pick_flight_ignores_non_flight_items() -> None:
    target = date(2026, 9, 1)
    meal = MealItem(source="google_places", source_id="m1", title="sushi")
    flight = _flight("2026-09-01T04:45:00", source_id="only-flight")
    picked = _pick_flight([meal, flight], target)
    assert picked is not None and picked.source_id == "only-flight"
