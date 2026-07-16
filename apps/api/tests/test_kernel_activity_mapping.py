"""The completeness rule, executable: every graph-touching planning activity
in the product decomposes onto the kernel's primitive set.

Each test names the surface activity it maps (agent tool, API route, or web
store action — see the activity → primitive table in doc/itin-time.md) and
performs it purely as primitives. An activity that cannot be expressed here is
a bug in the primitive set, to be fixed in Phase 1 while it is cheap.
"""

from datetime import date, time

from app.kernel import (
    Edge,
    Graph,
    Node,
    PinnedSchedule,
    Provenance,
    RelativeSchedule,
    add_edge,
    add_node,
    analyze,
    diff,
    fork,
    relative,
    schedule_node,
    set_anchor,
    set_status,
    unschedule_node,
    update_node,
    update_trip_meta,
)
from app.models.itinerary import EdgeType, NodeStatus, NodeType

ATHENS = "Europe/Athens"
AUG_1 = date(2026, 8, 1)


class TestContentActivities:
    def test_propose_card_and_save_to_collection(self):
        """agent propose_card / save_to_collection / save_link_to_collection /
        add_collection_note → add_node; unscheduled = the Collection."""
        graph = add_node(
            Graph(),
            Node(
                id="n1",
                type=NodeType.hotel,
                title="Villa Drakano",
                provenance=Provenance(source="serp", source_id="h_42"),
                content={"snapshot": {"rate": "EUR 1900"}},
            ),
        )
        graph = add_node(
            graph,
            Node(id="n2", type=NodeType.article, title="Why Olympus", content={"url": "https://…"}),
        )
        graph = add_node(graph, Node(id="n3", type=NodeType.note, title="No shellfish"))
        assert all(graph.nodes[n].schedule is None for n in ("n1", "n2", "n3"))

    def test_add_note_attached_to_a_card(self):
        """agent add_note(node_id=…) → add_node + add_edge(grouped_with)."""
        graph = add_node(Graph(), Node(id="hotel", type=NodeType.hotel))
        graph = add_node(graph, Node(id="note", type=NodeType.note, title="Late checkout"))
        graph = add_edge(
            graph, Edge(id="e1", from_id="note", to_id="hotel", type=EdgeType.grouped_with)
        )
        assert graph.edges["e1"].type is EdgeType.grouped_with

    def test_add_transfer_scheduled_on_arrival(self):
        """agent add_transfer → add_node with a schedule and route content."""
        graph = add_node(
            Graph(),
            Node(
                id="drive",
                type=NodeType.drive,
                title="SKG → Litochoro",
                schedule=relative(1, time(16, 0), ATHENS, duration_minutes=75),
                content={"route": {"km": 92}},
            ),
        )
        assert isinstance(graph.nodes["drive"].schedule, RelativeSchedule)

    def test_update_node_details(self):
        """agent update_node_details / advisor PATCH → update_node."""
        graph = add_node(Graph(), Node(id="n1", type=NodeType.meal, title="Dinner"))
        graph = update_node(graph, "n1", title="Dinner at Migdalies", content={"cost": 240})
        assert graph.nodes["n1"].title == "Dinner at Migdalies"

    def test_set_trip_brief_title_mood(self):
        """agent update_trip_details / advisor PATCH → update_trip_meta."""
        graph = update_trip_meta(Graph(), {"title": "Olympus in August", "mood": "alpine-dawn"})
        assert graph.meta["mood"] == "alpine-dawn"


class TestSchedulingActivities:
    def test_drag_on_the_timeline(self):
        """web moveNode(dayKey, minuteOfDay) → schedule_node."""
        graph = add_node(
            Graph(),
            Node(id="n1", type=NodeType.experience, schedule=relative(2, time(9, 0), ATHENS)),
        )
        graph, _ = schedule_node(graph, "n1", relative(3, time(14, 30), ATHENS))
        schedule = graph.nodes["n1"].schedule
        assert isinstance(schedule, RelativeSchedule)
        assert schedule.start.day_offset == 2
        assert schedule.start.wall_time == time(14, 30)

    def test_drag_back_to_collection(self):
        """web drag-to-collection → unschedule_node."""
        graph = add_node(
            Graph(),
            Node(id="n1", type=NodeType.experience, schedule=relative(2, time(9, 0), ATHENS)),
        )
        assert unschedule_node(graph, "n1").nodes["n1"].schedule is None

    def test_assemble_draft_is_a_batch_of_schedules(self):
        """agent assemble_draft(day_plan) → batch schedule_node, no new semantics."""
        graph = Graph()
        for node_id in ("a", "b", "c"):
            graph = add_node(graph, Node(id=node_id, type=NodeType.experience))
        day_plan = [(1, ["a"]), (2, ["b", "c"])]
        for day, node_ids in day_plan:
            for slot, node_id in enumerate(node_ids):
                graph, _ = schedule_node(
                    graph, node_id, relative(day, time(9 + slot * 3, 0), ATHENS)
                )
        assert graph.nodes["c"].schedule == relative(2, time(12, 0), ATHENS)

    def test_materialize_subgraph_children(self):
        """multi-day inventory expansion → add_node children + follows edges."""
        graph = add_node(Graph(), Node(id="pkg", type=NodeType.experience, title="3-day trek"))
        prev = "pkg"
        for i in (1, 2, 3):
            child = f"leg-{i}"
            graph = add_node(graph, Node(id=child, type=NodeType.experience, title=f"Leg {i}"))
            graph = add_edge(
                graph, Edge(id=f"e-{i}", from_id=prev, to_id=child, type=EdgeType.follows)
            )
            prev = child
        assert len(graph.edges) == 3

    def test_set_trip_timing_and_retime(self):
        """traveler update_trip_timing / advisor retime → set_anchor."""
        graph = add_node(
            Graph(),
            Node(id="n1", type=NodeType.experience, schedule=relative(4, time(9, 0), ATHENS)),
        )
        graph, _ = set_anchor(graph, AUG_1)
        graph, report = set_anchor(graph, date(2026, 8, 8))
        assert report.moved == ("n1",)


class TestLifecycleActivities:
    def test_traveler_approval_and_approve_all(self):
        """per-node approval / POST approve-all → set_status batch."""
        graph = Graph()
        for node_id in ("a", "b"):
            graph = add_node(graph, Node(id=node_id, type=NodeType.experience))
        for node_id in ("a", "b"):
            graph, _ = set_status(graph, node_id, NodeStatus.approved)
        assert all(n.status is NodeStatus.approved for n in graph.nodes.values())

    def test_discard_and_restore(self):
        graph = add_node(Graph(), Node(id="a", type=NodeType.experience))
        graph, _ = set_status(graph, "a", NodeStatus.discarded)
        graph, _ = set_status(graph, "a", NodeStatus.pending)
        assert graph.nodes["a"].status is NodeStatus.pending

    def test_book_confirm_demote(self):
        """money-gate book → confirm → advisor demote; the gate itself is a
        service-layer precondition, the kernel sees only the transitions."""
        graph = add_node(
            Graph(anchor_date=AUG_1),
            Node(id="a", type=NodeType.hotel, schedule=relative(1, time(15, 0), ATHENS)),
        )
        graph, _ = set_status(graph, "a", NodeStatus.booked)
        graph, _ = set_status(graph, "a", NodeStatus.confirmed)
        graph, report = set_status(graph, "a", NodeStatus.pending)
        assert report.auto_unpinned
        assert isinstance(graph.nodes["a"].schedule, RelativeSchedule)


class TestForkActivities:
    def test_fork_diff_reconcile_as_replay(self):
        """fork → diverge → diff → reconcile: accepted changes replay onto the
        trunk as ordinary primitives; rejected ones simply are not applied."""
        trunk = add_node(
            Graph(anchor_date=AUG_1),
            Node(id="keep", type=NodeType.experience, schedule=relative(2, time(9, 0), ATHENS)),
        )
        branch = fork(trunk)
        branch = add_node(branch, Node(id="new-dinner", type=NodeType.meal, title="Migdalies"))
        branch, _ = schedule_node(branch, "keep", relative(3, time(9, 0), ATHENS))

        changes = diff(trunk, branch)
        assert changes.added_nodes == ("new-dinner",)
        assert [c.node_id for c in changes.changed_nodes] == ["keep"]

        # Advisor accepts the added dinner, rejects the move of "keep".
        reconciled = trunk
        for node_id in changes.added_nodes:
            reconciled = add_node(reconciled, branch.nodes[node_id])
        assert "new-dinner" in reconciled.nodes
        assert reconciled.nodes["keep"].schedule == trunk.nodes["keep"].schedule


class TestFullScenario:
    def test_pillar_shaped_end_to_end(self):
        """Intake → collection → draft → dates → re-quote → book → retime:
        the e2e pillar flow as nothing but primitives."""
        # Conversational intake: undated trip, brief captured.
        graph = update_trip_meta(Graph(), {"title": "Olympus", "brief": "Solitude, effort, myth"})

        # The agent saves ideas to the Collection and drafts Day 2/Day 3.
        olympus = {"lat": 40.10, "lng": 22.50}
        graph = add_node(
            graph,
            Node(
                id="hike",
                type=NodeType.experience,
                title="Summit push",
                content={"location": olympus},
            ),
        )
        graph = add_node(
            graph,
            Node(
                id="hotel",
                type=NodeType.hotel,
                title="Litochoro inn",
                content={"location": olympus},
            ),
        )
        graph, _ = schedule_node(
            graph, "hike", relative(3, time(6, 0), ATHENS, duration_minutes=600)
        )
        graph, _ = schedule_node(graph, "hotel", relative(1, time(15, 0), ATHENS))

        # A quoted flight lands in the draft, relative like everything else.
        endpoints = {
            "from_location": {"lat": 42.21, "lng": -83.35},  # DTW
            "to_location": {"lat": 40.52, "lng": 22.97},  # SKG
        }
        graph = add_node(
            graph,
            Node(
                id="flight",
                type=NodeType.flight,
                title="DTW → SKG",
                provenance=Provenance(source="duffel", source_id="off_1", date_sensitive=True),
                schedule=relative(1, time(10, 0), ATHENS, duration_minutes=600),
                content={"offer_id": "off_1", **endpoints},
            ),
        )

        # Dates land: one field changes; the quote is flagged, never blocked.
        graph, report = set_anchor(graph, AUG_1)
        assert set(report.moved) == {"hike", "hotel", "flight"}
        assert report.marked_stale == ("flight",)

        # Re-quote clears the flag; booking pins the flight to the world.
        graph = update_node(graph, "flight", content={"offer_id": "off_2", **endpoints})
        graph, book = set_status(graph, "flight", NodeStatus.booked)
        assert book.auto_pinned

        # The trip moves a week earlier: the booking holds its Aug 1 arrival,
        # which now lands after the plan has already started — analysis says
        # so, and the caller surfaces it to the advisor. Affordance, not error.
        graph, retime = set_anchor(graph, date(2026, 7, 25))
        assert retime.held_pinned == ("flight",)
        assert isinstance(graph.nodes["flight"].schedule, PinnedSchedule)
        assert any(f.severity == "block" for f in analyze(graph))
