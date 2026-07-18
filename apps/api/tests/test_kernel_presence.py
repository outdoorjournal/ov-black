"""Nightly lodging presence: a stay is a span, nights are a derived view.

The modeling rule under test: a multi-night hotel is ONE node whose span
covers its nights — there are no per-night nodes, so "which roof tonight" is
coverage arithmetic, and the mid-stay excursion (keep the Tokyo room, sleep at
the ryokan) falls out of the latest-check-in tie rule with zero special
handling.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.kernel import (
    AbsoluteStamp,
    Graph,
    Node,
    PinnedSchedule,
    RelativeSchedule,
    RelativeStamp,
    add_node,
    lodging_at,
    nightly_lodging,
    relative,
)
from app.models.itinerary import NodeStatus, NodeType

TOKYO = "Asia/Tokyo"
AUG_1 = date(2026, 8, 1)


def _stay(node_id: str, check_in_day: int, check_out_day: int | None, *, hh_in: int = 15) -> Node:
    """A hotel node spanning check-in day → check-out day (None = open-ended)."""
    end = (
        RelativeStamp(day_offset=check_out_day - 1, wall_time=time(10, 0), tz_name=TOKYO)
        if check_out_day is not None
        else None
    )
    return Node(
        id=node_id,
        type=NodeType.hotel,
        title=f"Stay {node_id}",
        schedule=RelativeSchedule(
            start=RelativeStamp(
                day_offset=check_in_day - 1, wall_time=time(hh_in, 0), tz_name=TOKYO
            ),
            end=end,
        ),
    )


def _nights(graph: Graph) -> dict[int, str]:
    return {n.day_index: n.node_id for n in nightly_lodging(graph)}


class TestNightlyLodging:
    def test_multi_night_stay_covers_checkin_through_last_night(self):
        """Check in Day 2, check out Day 5 → nights 2, 3, 4. The checkout day
        is a morning, not a night."""
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 2, 5))
        assert _nights(graph) == {2: "h1", 3: "h1", 4: "h1"}

    def test_undated_trip_still_gets_day_labels(self):
        graph = add_node(Graph(), _stay("h1", 1, 3))
        nights = nightly_lodging(graph)
        assert [(n.day_index, n.on) for n in nights] == [(1, None), (2, None)]

    def test_dated_trip_carries_calendar_dates(self):
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 3))
        assert [n.on for n in nightly_lodging(graph)] == [date(2026, 8, 1), date(2026, 8, 2)]

    def test_same_day_hotel_change_goes_to_the_new_key(self):
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 3))
        graph = add_node(graph, _stay("h2", 3, 6))
        assert _nights(graph) == {1: "h1", 2: "h1", 3: "h2", 4: "h2", 5: "h2"}

    def test_mid_stay_excursion_wins_its_night_only(self):
        """The kept Tokyo room spans nights 1-5; a ryokan night on Day 3 owns
        Day 3 and the Tokyo room resumes after — no special modeling."""
        graph = add_node(Graph(anchor_date=AUG_1), _stay("tokyo", 1, 6))
        graph = add_node(graph, _stay("ryokan", 3, 4))
        assert _nights(graph) == {1: "tokyo", 2: "tokyo", 3: "ryokan", 4: "tokyo", 5: "tokyo"}

    def test_open_ended_stay_covers_through_trips_last_night(self):
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 2, None))
        dinner = Node(
            id="g1",
            type=NodeType.meal,
            title="Dinner",
            schedule=relative(4, time(20, 0), TOKYO, duration_minutes=90),
        )
        graph = add_node(graph, dinner)
        assert _nights(graph) == {2: "h1", 3: "h1", 4: "h1"}

    def test_discarded_and_day_use_stays_cover_nothing(self):
        day_use = _stay("h-day", 2, 2)
        discarded = Node(
            id="h-disc",
            type=NodeType.hotel,
            title="Discarded",
            status=NodeStatus.discarded,
            schedule=RelativeSchedule(
                start=RelativeStamp(day_offset=0, wall_time=time(15, 0), tz_name=TOKYO),
                end=RelativeStamp(day_offset=4, wall_time=time(10, 0), tz_name=TOKYO),
            ),
        )
        graph = add_node(add_node(Graph(anchor_date=AUG_1), day_use), discarded)
        assert _nights(graph) == {}

    def test_pinned_stay_on_undated_trip_is_skipped(self):
        pinned = Node(
            id="h1",
            type=NodeType.hotel,
            title="Pinned",
            schedule=PinnedSchedule(
                start=AbsoluteStamp(date(2026, 8, 2), time(15, 0), TOKYO),
                end=AbsoluteStamp(date(2026, 8, 4), time(10, 0), TOKYO),
            ),
        )
        assert nightly_lodging(add_node(Graph(), pinned)) == ()
        # The same stay on a dated trip resolves to its offsets.
        dated = add_node(Graph(anchor_date=AUG_1), pinned)
        assert _nights(dated) == {2: "h1", 3: "h1"}


class TestLodgingAt:
    def _graph(self) -> Graph:
        graph = add_node(Graph(anchor_date=AUG_1), _stay("tokyo", 1, 6))
        return add_node(graph, _stay("ryokan", 3, 4))

    def _at(self, day: int, hh: int) -> datetime:
        return datetime(2026, 8, day, hh, 0, tzinfo=ZoneInfo(TOKYO))

    def test_before_first_checkin_there_is_no_base(self):
        """Lunch on arrival day: a room tonight, but not based anywhere yet —
        'you're near your hotel' is only true past the first check-in."""
        assert lodging_at(self._graph(), self._at(1, 12)) is None

    def test_during_the_stay_the_base_is_the_hotel(self):
        node = lodging_at(self._graph(), self._at(2, 13))
        assert node is not None and node.id == "tokyo"

    def test_excursion_night_rebases_to_the_latest_checkin(self):
        node = lodging_at(self._graph(), self._at(3, 20))
        assert node is not None and node.id == "ryokan"
        back = lodging_at(self._graph(), self._at(4, 20))
        assert back is not None and back.id == "tokyo"

    def test_after_checkout_the_base_is_gone(self):
        assert lodging_at(self._graph(), self._at(6, 12)) is None

    def test_undated_trip_has_no_instants_to_cover(self):
        graph = add_node(Graph(), _stay("h1", 1, 3))
        assert lodging_at(graph, self._at(2, 12)) is None
