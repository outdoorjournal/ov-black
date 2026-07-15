"""The flight-feasibility floor (``agent.flight_timing``).

Regression guard for the incident where a Detroit→Thessaloniki outbound was
proposed that *arrived* Aug 15 04:34 — after the plan's first item began Aug 14
15:00 — and the model narrated the miss away. The block must fire on that shape
and stay quiet on a feasible one.
"""

from __future__ import annotations

from agent.flight_timing import flight_conflicts


# Coordinates used across the fixtures.
_OLYMPUS = {"lat": 40.0885, "lng": 22.3489}  # trip base
_DTW = {"lat": 42.2143, "lng": -83.3544}  # home, ~8000 km away
_SKG = {"lat": 40.5201, "lng": 22.9713}  # Thessaloniki, ~55 km from base
_JTR = {"lat": 36.3992, "lng": 25.4793}  # Santorini, internal hop (<1000 km)


def _flight(
    node_id: str,
    depart: str,
    arrive: str,
    title: str = "DTW → SKG",
    from_loc: dict | None = None,
    to_loc: dict | None = None,
) -> dict:
    return {
        "id": node_id,
        "type": "flight",
        "title": title,
        "starts_at": depart,
        "metadata": {
            "depart_at": depart,
            "arrive_at": arrive,
            "from_location": _DTW if from_loc is None else from_loc,
            "to_location": _SKG if to_loc is None else to_loc,
        },
    }


def _item(node_id: str, start: str, duration: int, type_: str = "experience", title: str = "item") -> dict:
    return {
        "id": node_id,
        "type": type_,
        "title": title,
        "starts_at": start,
        "duration_minutes": duration,
        "metadata": {"location": _OLYMPUS},
    }


# The exact incident: first item Aug 14 15:00 (+03:00), outbound arrives Aug 15
# 04:34 — the morning AFTER — while departing Aug 14 10:03 (−04:00).
_FIRST_ITEM = _item(
    "exp-1", "2026-08-14T15:00:00+03:00", 8640, title="Trip to Mount Olympus"
)
_LATE_OUTBOUND = _flight("f-out", "2026-08-14T10:03:00-04:00", "2026-08-15T04:34:00+03:00")


def test_outbound_arriving_after_first_item_blocks() -> None:
    conflicts = flight_conflicts([_FIRST_ITEM, _LATE_OUTBOUND])
    blocks = [c for c in conflicts if c.severity == "block"]
    assert len(blocks) == 1
    assert blocks[0].node_id == "f-out"
    assert blocks[0].leg == "outbound"
    assert "arrives" in blocks[0].detail


def test_outbound_landing_the_day_before_is_clean() -> None:
    # Same plan, but depart Aug 13 so arrival Aug 14 08:00 clears the 15:00 item.
    good = _flight("f-out", "2026-08-13T10:03:00-04:00", "2026-08-14T08:00:00+03:00")
    assert flight_conflicts([_FIRST_ITEM, good]) == []


def test_tight_but_possible_arrival_warns_not_blocks() -> None:
    # Arrives 90 min before the item — physically possible, but tight.
    tight = _flight("f-out", "2026-08-14T00:00:00-04:00", "2026-08-14T13:30:00+03:00")
    conflicts = flight_conflicts([_FIRST_ITEM, tight])
    assert [c.severity for c in conflicts] == ["warn"]
    assert conflicts[0].leg == "outbound"


def test_return_departing_before_last_item_ends_blocks() -> None:
    last = _item("exp-last", "2026-08-28T12:00:00+03:00", 300, title="last day")  # ends 17:00
    # Return leaves 15:00 — before the 17:00 finish.
    ret = _flight(
        "f-ret", "2026-08-28T15:00:00+03:00", "2026-08-28T22:00:00-04:00",
        title="SKG → DTW", from_loc=_SKG, to_loc=_DTW,
    )
    conflicts = flight_conflicts([_FIRST_ITEM, last, ret])
    blocks = [c for c in conflicts if c.severity == "block"]
    assert [(c.node_id, c.leg) for c in blocks] == [("f-ret", "return")]


def test_full_roundtrip_both_legs_feasible_is_clean() -> None:
    last = _item("exp-last", "2026-08-27T12:00:00+03:00", 300, title="Thessaloniki")
    out = _flight("f-out", "2026-08-13T10:03:00-04:00", "2026-08-14T08:00:00+03:00")
    ret = _flight(
        "f-ret", "2026-08-28T20:54:00+03:00", "2026-08-29T01:25:00-04:00",
        title="SKG → DTW", from_loc=_SKG, to_loc=_DTW,
    )
    assert flight_conflicts([_FIRST_ITEM, last, out, ret]) == []


def test_intra_trip_hop_is_ignored() -> None:
    # A flight wholly inside the trip window is the pacing analyzer's concern,
    # not the arrival/departure floor's.
    hop = _flight(
        "f-hop", "2026-08-20T09:00:00+03:00", "2026-08-20T10:00:00+03:00",
        title="SKG → JTR", from_loc=_SKG, to_loc=_JTR,
    )
    assert flight_conflicts([_FIRST_ITEM, hop]) == []


def test_no_dated_items_no_conflicts() -> None:
    # Dateless plan (everything in the Collection) — nothing to anchor against.
    assert flight_conflicts([_LATE_OUTBOUND]) == []
