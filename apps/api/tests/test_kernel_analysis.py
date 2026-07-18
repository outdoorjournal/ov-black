"""Kernel analysis: the golden bug cases, overlaps, follows-gaps, staleness.

The Detroit→Thessaloniki case is the incident that motivated the feasibility
floor (see apps/agent flight_timing): an outbound that *arrived* the morning
after the plan's first item began, narrated away as fine. Here it runs on
resolved instants, so the cross-zone comparison is exact by construction.
"""

from datetime import date, time

from app.kernel import (
    AbsoluteStamp,
    Edge,
    Graph,
    Node,
    PinnedSchedule,
    Provenance,
    add_edge,
    add_node,
    analyze,
    diff,
    fork,
    relative,
    remove_node,
    schedule_node,
    set_anchor,
    set_status,
)
from app.models.itinerary import EdgeType, NodeStatus, NodeType

ATHENS = "Europe/Athens"
DETROIT = "America/Detroit"
AUG_1 = date(2026, 8, 1)

# Litochoro (Olympus base) and the two airports.
OLYMPUS = {"lat": 40.10, "lng": 22.50}
DTW = {"lat": 42.21, "lng": -83.35}
SKG = {"lat": 40.52, "lng": 22.97}


def _ground(node_id: str, day: int, hh: int, *, duration: int = 120) -> Node:
    return Node(
        id=node_id,
        type=NodeType.experience,
        title=f"Ground {node_id}",
        schedule=relative(day, time(hh, 0), ATHENS, duration_minutes=duration),
        content={"location": OLYMPUS},
    )


def _flight(
    node_id: str,
    depart: AbsoluteStamp,
    arrive: AbsoluteStamp,
    *,
    outbound: bool,
) -> Node:
    return Node(
        id=node_id,
        type=NodeType.flight,
        title=f"Flight {node_id}",
        schedule=PinnedSchedule(start=depart, end=arrive),
        content=(
            {"from_location": DTW, "to_location": SKG}
            if outbound
            else {"from_location": SKG, "to_location": DTW}
        ),
    )


def _codes(graph: Graph) -> set[str]:
    return {f.code for f in analyze(graph)}


class TestFlightFeasibility:
    def test_detroit_thessaloniki_golden_block(self):
        """Departs Aug 14 10:03 Detroit, arrives Aug 15 04:34 Athens — but the
        plan's first item begins Aug 14 15:00 Athens. Physically impossible."""
        graph = Graph(anchor_date=date(2026, 8, 14))
        graph = add_node(graph, _ground("g1", 1, 15))
        graph = add_node(
            graph,
            _flight(
                "fl-out",
                AbsoluteStamp(date(2026, 8, 14), time(10, 3), DETROIT),
                AbsoluteStamp(date(2026, 8, 15), time(4, 34), ATHENS),
                outbound=True,
            ),
        )
        blocks = [f for f in analyze(graph) if f.severity == "block"]
        assert len(blocks) == 1
        assert blocks[0].code == "flight_infeasible"
        assert "fl-out" in blocks[0].node_ids

    def test_feasible_roundtrip_is_clean(self):
        graph = Graph(anchor_date=AUG_1)
        graph = add_node(graph, _ground("g1", 1, 15))
        graph = add_node(graph, _ground("g2", 9, 9))
        graph = add_node(
            graph,
            _flight(
                "fl-out",
                AbsoluteStamp(date(2026, 7, 31), time(18, 0), DETROIT),
                AbsoluteStamp(date(2026, 8, 1), time(9, 0), ATHENS),
                outbound=True,
            ),
        )
        graph = add_node(
            graph,
            _flight(
                "fl-back",
                AbsoluteStamp(date(2026, 8, 9), time(18, 0), ATHENS),
                AbsoluteStamp(date(2026, 8, 9), time(22, 0), DETROIT),
                outbound=False,
            ),
        )
        assert not [f for f in analyze(graph) if f.code.startswith("flight")]

    def test_tight_arrival_warns_without_blocking(self):
        graph = Graph(anchor_date=AUG_1)
        graph = add_node(graph, _ground("g1", 1, 15))
        graph = add_node(
            graph,
            _flight(
                "fl-out",
                AbsoluteStamp(date(2026, 7, 31), time(20, 0), DETROIT),
                AbsoluteStamp(date(2026, 8, 1), time(13, 0), ATHENS),  # 120 min margin
                outbound=True,
            ),
        )
        findings = [f for f in analyze(graph) if f.code == "flight_tight"]
        assert len(findings) == 1
        assert findings[0].severity == "warn"

    def test_retime_stranding_a_booked_return_is_found(self):
        """The plan moves a week later; the booked return holds its dates and
        now departs before the last item ends — reported, never rewritten."""
        graph = Graph(anchor_date=AUG_1)
        graph = add_node(graph, _ground("g1", 1, 15))
        graph = add_node(graph, _ground("g2", 8, 9))
        return_flight = _flight(
            "fl-back",
            AbsoluteStamp(date(2026, 8, 9), time(18, 0), ATHENS),
            AbsoluteStamp(date(2026, 8, 9), time(22, 0), DETROIT),
            outbound=False,
        )
        graph = add_node(graph, return_flight)
        graph, _ = set_status(graph, "fl-back", NodeStatus.booked)
        assert not [f for f in analyze(graph) if f.severity == "block"]

        graph, report = set_anchor(graph, date(2026, 8, 8))
        assert report.held_pinned == ("fl-back",)
        blocks = [f for f in analyze(graph) if f.severity == "block"]
        assert len(blocks) == 1
        assert "fl-back" in blocks[0].node_ids


class TestOverlaps:
    def test_overlapping_ground_items_warn(self):
        graph = add_node(Graph(anchor_date=AUG_1), _ground("g1", 2, 9))
        graph = add_node(graph, _ground("g2", 2, 10))
        assert "overlap" in _codes(graph)

    def test_alternatives_are_allowed_to_overlap(self):
        """The graph knows the overlap is intentional — formalism paying off."""
        graph = add_node(Graph(anchor_date=AUG_1), _ground("g1", 2, 9))
        graph = add_node(graph, _ground("g2", 2, 10))
        graph = add_edge(
            graph, Edge(id="e1", from_id="g2", to_id="g1", type=EdgeType.alternative_to)
        )
        assert "overlap" not in _codes(graph)

    def test_unpinned_trip_analyzes_on_the_provisional_calendar(self):
        graph = add_node(Graph(), _ground("g1", 2, 9))
        graph = add_node(graph, _ground("g2", 2, 10))
        assert "overlap" in _codes(graph)


def _stay(
    node_id: str,
    check_in_day: int,
    check_out_day: int,
    *,
    hh_in: int = 15,
    content: dict | None = None,
) -> Node:
    from app.kernel import RelativeSchedule, RelativeStamp

    return Node(
        id=node_id,
        type=NodeType.hotel,
        title=f"Stay {node_id}",
        schedule=RelativeSchedule(
            start=RelativeStamp(
                day_offset=check_in_day - 1, wall_time=time(hh_in, 0), tz_name=ATHENS
            ),
            end=RelativeStamp(day_offset=check_out_day - 1, wall_time=time(10, 0), tz_name=ATHENS),
        ),
        content={"location": OLYMPUS, **(content or {})},
    )


class TestLodgingIsPresenceNotEvent:
    def test_a_stay_never_overlaps_the_dinners_it_contains(self):
        """A 4-night span holding every dinner of the trip is the point of a
        hotel, not a conflict."""
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5))
        graph = add_node(graph, _ground("g1", 2, 20))
        graph = add_node(graph, _ground("g2", 3, 20))
        assert "overlap" not in _codes(graph)

    def test_arriving_after_checkin_time_is_not_infeasible(self):
        """Check-in is a window, not a start you can miss: a flight landing
        after the 15:00 check-in but before the evening's first event is fine."""
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5))
        graph = add_node(graph, _ground("g1", 1, 21))
        graph = add_node(
            graph,
            _flight(
                "fl-out",
                AbsoluteStamp(date(2026, 7, 31), time(20, 0), DETROIT),
                AbsoluteStamp(date(2026, 8, 1), time(18, 0), ATHENS),
                outbound=True,
            ),
        )
        assert "flight_infeasible" not in _codes(graph)

    def test_early_return_before_checkout_is_not_infeasible(self):
        """Checking out early for a morning flight is normal — the checkout
        wall time is not an end the traveler must stay for."""
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5))
        graph = add_node(graph, _ground("g1", 2, 15))
        graph = add_node(
            graph,
            _flight(
                "fl-back",
                AbsoluteStamp(date(2026, 8, 5), time(7, 0), ATHENS),
                AbsoluteStamp(date(2026, 8, 5), time(11, 0), DETROIT),
                outbound=False,
            ),
        )
        assert "flight_infeasible" not in _codes(graph)


class TestLodgingFindings:
    def _with_arrival(self, cutoff: str | None, arrive: time, arrive_on: date) -> Graph:
        content = {"check_in_cutoff": cutoff} if cutoff is not None else None
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5, content=content))
        return add_node(
            graph,
            _flight(
                "fl-out",
                AbsoluteStamp(date(2026, 7, 31), time(20, 0), DETROIT),
                AbsoluteStamp(arrive_on, arrive, ATHENS),
                outbound=True,
            ),
        )

    def test_landing_after_the_desk_cutoff_warns(self):
        graph = self._with_arrival("22:00", time(23, 30), date(2026, 8, 1))
        findings = [f for f in analyze(graph) if f.code == "lodging_checkin_late"]
        assert len(findings) == 1
        assert findings[0].severity == "warn"
        assert set(findings[0].node_ids) == {"h1", "fl-out"}

    def test_after_midnight_landing_still_counts_as_arrival_night(self):
        graph = self._with_arrival("22:00", time(1, 30), date(2026, 8, 2))
        assert "lodging_checkin_late" in _codes(graph)

    def test_landing_before_the_cutoff_is_clean(self):
        graph = self._with_arrival("22:00", time(20, 0), date(2026, 8, 1))
        assert "lodging_checkin_late" not in _codes(graph)

    def test_no_cutoff_means_a_24h_desk(self):
        graph = self._with_arrival(None, time(23, 30), date(2026, 8, 1))
        assert "lodging_checkin_late" not in _codes(graph)

    def test_event_running_past_checkout_warns(self):
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5))
        graph = add_node(graph, _ground("g1", 5, 8, duration=240))  # 08:00-12:00, checkout 10:00
        findings = [f for f in analyze(graph) if f.code == "lodging_checkout_conflict"]
        assert len(findings) == 1
        assert set(findings[0].node_ids) == {"h1", "g1"}

    def test_morning_event_ending_before_checkout_is_clean(self):
        graph = add_node(Graph(anchor_date=AUG_1), _stay("h1", 1, 5))
        graph = add_node(graph, _ground("g1", 5, 8, duration=90))  # ends 09:30
        assert "lodging_checkout_conflict" not in _codes(graph)


class TestFollowsGap:
    def test_short_gap_after_predecessor_warns(self):
        graph = add_node(Graph(anchor_date=AUG_1), _ground("g1", 2, 9, duration=60))
        graph = add_node(graph, _ground("g2", 2, 10, duration=60))  # starts as g1 ends
        graph = add_edge(
            graph,
            Edge(id="e1", from_id="g1", to_id="g2", type=EdgeType.follows, min_gap_minutes=45),
        )
        findings = [f for f in analyze(graph) if f.code == "follows_gap"]
        assert len(findings) == 1
        assert "45" in findings[0].message


class TestStaleness:
    def test_stale_nodes_surface_as_info(self):
        flight = Node(
            id="fl-1",
            type=NodeType.flight,
            title="Quoted",
            schedule=relative(1, time(10, 0), ATHENS),
            provenance=Provenance(source="duffel", source_id="off_1", date_sensitive=True),
        )
        graph = add_node(Graph(anchor_date=AUG_1), flight)
        graph, _ = schedule_node(graph, "fl-1", relative(3, time(10, 0), ATHENS))
        stale = [f for f in analyze(graph) if f.code == "stale"]
        assert len(stale) == 1
        assert stale[0].node_ids == ("fl-1",)


class TestDiff:
    def test_fork_divergence_is_derivable(self):
        base = add_node(Graph(anchor_date=AUG_1), _ground("g1", 2, 9))
        base = add_node(base, _ground("g2", 3, 9))
        branch = fork(base)
        branch = add_node(branch, _ground("g3", 4, 9))
        branch = remove_node(branch, "g2")
        branch, _ = schedule_node(branch, "g1", relative(5, time(9, 0), ATHENS))
        result = diff(base, branch)
        assert result.added_nodes == ("g3",)
        assert result.removed_nodes == ("g2",)
        assert [c.node_id for c in result.changed_nodes] == ["g1"]
        assert result.changed_nodes[0].fields == ("schedule",)
        # And the fork never disturbed the trunk.
        assert diff(base, base).empty
