"""GraphSnapshot + diff (offline state tracking)."""

from _helpers import make_graph, make_node
from ovb.scenario import GraphSnapshot

ITIN = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "cccccccc-0000-0000-0000-000000000003"
E1 = "eeeeeeee-0000-0000-0000-000000000001"


def test_snapshot_indexes_and_groups_by_status() -> None:
    g = make_graph(
        ITIN,
        nodes=[make_node(A, ITIN, status="approved"), make_node(B, ITIN, status="proposed")],
    )
    snap = GraphSnapshot.of(g)
    assert set(snap.nodes) == {A, B}
    assert snap.statuses() == {A: "approved", B: "proposed"}
    assert [str(n.id) for n in snap.by_status("approved")] == [A]
    assert snap.status == "draft"


def test_diff_reports_added_removed_changed_and_edges() -> None:
    before = GraphSnapshot.of(
        make_graph(ITIN, nodes=[make_node(A, ITIN, status="proposed"), make_node(B, ITIN)])
    )
    after = GraphSnapshot.of(
        make_graph(
            ITIN,
            nodes=[make_node(A, ITIN, status="approved"), make_node(C, ITIN)],
            edges=[
                {
                    "id": E1,
                    "itinerary_id": ITIN,
                    "from_node_id": A,
                    "to_node_id": C,
                    "type": "follows",
                    "metadata": {},
                }
            ],
        )
    )
    diff = before.diff(after)
    assert diff.added_nodes == [C]
    assert diff.removed_nodes == [B]
    assert set(diff.changed_nodes) == {A}
    assert "status" in diff.changed_nodes[A]
    assert diff.changed_nodes[A]["status"][1] == "approved"
    assert diff.added_edges == [E1]
    assert not diff.empty
    assert "node" in diff.summary()


def test_identical_snapshots_diff_empty() -> None:
    g = make_graph(ITIN, nodes=[make_node(A, ITIN)])
    diff = GraphSnapshot.of(g).diff(GraphSnapshot.of(g))
    assert diff.empty and diff.summary() == "no change"
