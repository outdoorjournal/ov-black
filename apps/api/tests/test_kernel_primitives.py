"""Kernel primitives: structural invariants, the pin lifecycle, revalidation
marking, and the one-field retime."""

from datetime import date, time

import pytest
from app.kernel import (
    Edge,
    Graph,
    KernelViolation,
    Node,
    PinnedSchedule,
    Provenance,
    RelativeSchedule,
    add_edge,
    add_node,
    clear_anchor,
    pin_node,
    pin_schedule,
    relative,
    remove_edge,
    remove_node,
    schedule_node,
    set_anchor,
    set_status,
    unpin_node,
    unschedule_node,
    update_node,
    update_trip_meta,
)
from app.models.itinerary import EdgeType, NodeStatus, NodeType

ATHENS = "Europe/Athens"
AUG_1 = date(2026, 8, 1)


def _experience(node_id: str = "exp-1", **kwargs) -> Node:
    return Node(id=node_id, type=NodeType.experience, title="Summit hike", **kwargs)


def _quoted_flight(node_id: str = "fl-1", **kwargs) -> Node:
    kwargs.setdefault(
        "provenance", Provenance(source="duffel", source_id="off_1", date_sensitive=True)
    )
    kwargs.setdefault("schedule", relative(1, time(10, 0), ATHENS, duration_minutes=600))
    return Node(id=node_id, type=NodeType.flight, title="DTW → SKG", **kwargs)


class TestContentPrimitives:
    def test_duplicate_node_is_a_violation(self):
        graph = add_node(Graph(), _experience())
        with pytest.raises(KernelViolation) as exc:
            add_node(graph, _experience())
        assert exc.value.code == "duplicate_node"

    def test_article_cannot_be_scheduled(self):
        article = Node(
            id="art-1",
            type=NodeType.article,
            schedule=relative(1, time(9, 0), ATHENS),
        )
        with pytest.raises(KernelViolation) as exc:
            add_node(Graph(), article)
        assert exc.value.code == "unschedulable_type"

    def test_remove_node_cascades_incident_edges(self):
        graph = add_node(Graph(), _experience("a"))
        graph = add_node(graph, _experience("b"))
        graph = add_edge(graph, Edge(id="e1", from_id="a", to_id="b", type=EdgeType.follows))
        graph = remove_node(graph, "a")
        assert "a" not in graph.nodes
        assert graph.edges == {}

    def test_edge_endpoints_must_exist(self):
        graph = add_node(Graph(), _experience("a"))
        with pytest.raises(KernelViolation) as exc:
            add_edge(graph, Edge(id="e1", from_id="a", to_id="ghost", type=EdgeType.follows))
        assert exc.value.code == "unknown_node"

    def test_self_edge_is_a_violation(self):
        graph = add_node(Graph(), _experience("a"))
        with pytest.raises(KernelViolation) as exc:
            add_edge(graph, Edge(id="e1", from_id="a", to_id="a", type=EdgeType.follows))
        assert exc.value.code == "self_edge"

    def test_remove_unknown_edge_is_a_violation(self):
        with pytest.raises(KernelViolation):
            remove_edge(Graph(), "ghost")

    def test_update_trip_meta_merges(self):
        graph = update_trip_meta(Graph(meta={"title": "Draft"}), {"brief": "Solitude"})
        assert graph.meta == {"title": "Draft", "brief": "Solitude"}

    def test_primitives_never_mutate_the_input_graph(self):
        base = add_node(Graph(), _experience("a"))
        add_node(base, _experience("b"))
        remove_node(base, "a")
        assert set(base.nodes) == {"a"}


class TestStatusLifecycle:
    def test_illegal_transition_is_a_violation(self):
        graph = add_node(Graph(), _experience())
        with pytest.raises(KernelViolation) as exc:
            set_status(graph, "exp-1", NodeStatus.confirmed)
        assert exc.value.code == "illegal_transition"

    def test_discarded_can_only_be_restored(self):
        graph = add_node(Graph(), _experience(status=NodeStatus.discarded))
        with pytest.raises(KernelViolation):
            set_status(graph, "exp-1", NodeStatus.approved)
        graph, _ = set_status(graph, "exp-1", NodeStatus.pending)
        assert graph.nodes["exp-1"].status is NodeStatus.pending

    def test_booking_pins_a_relative_schedule(self):
        graph = Graph(anchor_date=AUG_1)
        graph = add_node(graph, _quoted_flight())
        graph, report = set_status(graph, "fl-1", NodeStatus.booked)
        assert report.auto_pinned
        schedule = graph.nodes["fl-1"].schedule
        assert isinstance(schedule, PinnedSchedule)
        assert schedule.start.on == AUG_1

    def test_booking_on_an_undated_trip_is_a_violation(self):
        graph = add_node(Graph(), _quoted_flight())
        with pytest.raises(KernelViolation) as exc:
            set_status(graph, "fl-1", NodeStatus.booked)
        assert exc.value.code == "book_undated"

    def test_booking_an_unscheduled_node_needs_no_pin(self):
        graph = add_node(Graph(anchor_date=AUG_1), _experience())
        graph, report = set_status(graph, "exp-1", NodeStatus.booked)
        assert not report.auto_pinned
        assert graph.nodes["exp-1"].schedule is None

    def test_cancelling_a_booking_unpins(self):
        graph = add_node(Graph(anchor_date=AUG_1), _quoted_flight())
        graph, _ = set_status(graph, "fl-1", NodeStatus.booked)
        graph, report = set_status(graph, "fl-1", NodeStatus.pending)
        assert report.auto_unpinned
        assert isinstance(graph.nodes["fl-1"].schedule, RelativeSchedule)

    def test_booked_to_confirmed_keeps_the_pin(self):
        graph = add_node(Graph(anchor_date=AUG_1), _quoted_flight())
        graph, _ = set_status(graph, "fl-1", NodeStatus.booked)
        graph, report = set_status(graph, "fl-1", NodeStatus.confirmed)
        assert not report.auto_pinned and not report.auto_unpinned
        assert isinstance(graph.nodes["fl-1"].schedule, PinnedSchedule)


class TestSchedulingAndRevalidation:
    def test_first_placement_of_a_quote_is_not_stale(self):
        graph = add_node(Graph(), _quoted_flight(schedule=None))
        graph, report = schedule_node(graph, "fl-1", relative(1, time(10, 0), ATHENS))
        assert not report.marked_stale
        assert not graph.nodes["fl-1"].needs_revalidation

    def test_moving_a_date_sensitive_quote_marks_it_stale(self):
        graph = add_node(Graph(), _quoted_flight())
        graph, report = schedule_node(graph, "fl-1", relative(3, time(10, 0), ATHENS))
        assert report.marked_stale
        assert graph.nodes["fl-1"].needs_revalidation

    def test_moving_a_non_sensitive_node_does_not_mark(self):
        graph = add_node(Graph(), _experience(schedule=relative(1, time(9, 0), ATHENS)))
        graph, report = schedule_node(graph, "exp-1", relative(2, time(9, 0), ATHENS))
        assert not report.marked_stale

    def test_fresh_snapshot_clears_the_stale_mark(self):
        """Re-quoting against the provider is an update_node with new content."""
        graph = add_node(Graph(), _quoted_flight())
        graph, _ = schedule_node(graph, "fl-1", relative(3, time(10, 0), ATHENS))
        graph = update_node(graph, "fl-1", content={"offer_id": "off_2"})
        assert not graph.nodes["fl-1"].needs_revalidation

    def test_committed_nodes_cannot_go_relative(self):
        graph = add_node(Graph(anchor_date=AUG_1), _quoted_flight())
        graph, _ = set_status(graph, "fl-1", NodeStatus.booked)
        with pytest.raises(KernelViolation) as exc:
            schedule_node(graph, "fl-1", relative(5, time(10, 0), ATHENS))
        assert exc.value.code == "committed_unpin"

    def test_committed_nodes_cannot_be_unscheduled(self):
        graph = add_node(Graph(anchor_date=AUG_1), _quoted_flight())
        graph, _ = set_status(graph, "fl-1", NodeStatus.booked)
        with pytest.raises(KernelViolation) as exc:
            unschedule_node(graph, "fl-1")
        assert exc.value.code == "committed_unschedule"

    def test_unschedule_returns_to_collection(self):
        graph = add_node(Graph(), _experience(schedule=relative(1, time(9, 0), ATHENS)))
        graph = unschedule_node(graph, "exp-1")
        assert graph.nodes["exp-1"].schedule is None

    def test_explicit_pin_and_unpin(self):
        graph = add_node(
            Graph(anchor_date=AUG_1), _experience(schedule=relative(2, time(20, 0), ATHENS))
        )
        graph = pin_node(graph, "exp-1")
        schedule = graph.nodes["exp-1"].schedule
        assert isinstance(schedule, PinnedSchedule)
        assert schedule.start.on == date(2026, 8, 2)
        graph = unpin_node(graph, "exp-1")
        assert graph.nodes["exp-1"].schedule == relative(2, time(20, 0), ATHENS)

    def test_pin_without_anchor_is_a_violation(self):
        graph = add_node(Graph(), _experience(schedule=relative(2, time(20, 0), ATHENS)))
        with pytest.raises(KernelViolation) as exc:
            pin_node(graph, "exp-1")
        assert exc.value.code == "pin_undated"


class TestSetAnchor:
    def _trip(self) -> Graph:
        graph = Graph(anchor_date=AUG_1)
        graph = add_node(graph, _experience(schedule=relative(4, time(9, 0), ATHENS)))
        graph = add_node(graph, _quoted_flight())
        booked = Node(
            id="fl-booked",
            type=NodeType.flight,
            title="Return",
            status=NodeStatus.booked,
            schedule=pin_schedule(relative(10, time(18, 0), ATHENS), AUG_1),
        )
        return add_node(graph, booked)

    def test_same_anchor_is_a_no_op(self):
        graph = self._trip()
        updated, report = set_anchor(graph, AUG_1)
        assert updated is graph
        assert report.moved == ()

    def test_retime_is_one_field_and_reports_the_consequences(self):
        graph = self._trip()
        updated, report = set_anchor(graph, date(2026, 8, 8))
        assert updated.anchor_date == date(2026, 8, 8)
        # Relative schedules are untouched by construction — that is the model.
        assert updated.nodes["exp-1"].schedule == graph.nodes["exp-1"].schedule
        assert set(report.moved) == {"exp-1", "fl-1"}
        # The booked flight held its calendar dates; the caller decides what
        # to do about it — affordance, not rejection.
        assert report.held_pinned == ("fl-booked",)
        assert updated.nodes["fl-booked"].schedule == graph.nodes["fl-booked"].schedule
        # The proposed flight moved off its quoted dates → flagged, not blocked.
        assert report.marked_stale == ("fl-1",)
        assert updated.nodes["fl-1"].needs_revalidation

    def test_stale_marks_do_not_double_report(self):
        graph = self._trip()
        graph, _ = set_anchor(graph, date(2026, 8, 8))
        _, second = set_anchor(graph, date(2026, 8, 15))
        assert second.marked_stale == ()  # already flagged; still moved
        assert "fl-1" in second.moved

    def test_retime_paths_converge(self):
        """set_anchor(d1) then set_anchor(d2) leaves the same schedules and
        anchor as set_anchor(d2) directly."""
        via_hop, _ = set_anchor(self._trip(), date(2026, 8, 8))
        via_hop, _ = set_anchor(via_hop, date(2026, 9, 1))
        direct, _ = set_anchor(self._trip(), date(2026, 9, 1))
        assert via_hop.anchor_date == direct.anchor_date
        for node_id in direct.nodes:
            assert via_hop.nodes[node_id].schedule == direct.nodes[node_id].schedule

    def test_clear_anchor_unpins_the_trip_not_the_bookings(self):
        graph = self._trip()
        updated, report = clear_anchor(graph)
        assert updated.anchor_date is None
        assert report.held_pinned == ("fl-booked",)
        assert isinstance(updated.nodes["fl-booked"].schedule, PinnedSchedule)
