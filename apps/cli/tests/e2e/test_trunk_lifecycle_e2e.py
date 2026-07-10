"""Trunk lifecycle — the official trunk + short-lived forks model, end to end.

The full loop the refactor promises (doc/thoughts.md → trunk/fork plan):

  1. advisor creates a trip → an official trunk, ``display_status=in_studio``
  2. advisor forks and builds privately → trunk stays empty; a traveler content
     write on the trunk is refused 409 ``fork_required``
  3. advisor publishes (reconcile ``accept_all``) → content lands ``pending``
     on the trunk, ``display_status=with_traveler``
  4. the linked traveler reads the trunk; their own content edit on it is
     refused; they fork and edit their working copy instead
  5. traveler requests a merge; advisor diffs and reconciles ``accept_all``
  6. traveler approves per-node, then ``approve-all`` → ``approved``; the
     non-approvable annotation kinds are untouched

Booking an approved node (the pillar-6 money gate) is covered by
``test_pillar6_invoice_book_e2e.py`` and not repeated here.
"""

from __future__ import annotations

import pytest

from ovb.errors import ApiError
from ovb.invariants import assert_no_violations, fork_lineage_holds, graph_integrity
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_trunk_and_fork_full_loop(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    client_id = linked_traveler_client_id

    # 1. Advisor creates the trip — an empty official trunk.
    trunk = await advisor.create_itinerary(
        title="Trunk lifecycle e2e",
        client_id=client_id,
        timing_kind="exact",
        date_start="2027-05-03",
        date_end="2027-05-06",
    )
    trunk_id = str(trunk.id)
    graph = await advisor.get_graph(trunk_id)
    assert str(graph.itinerary.display_status) == "in_studio"
    assert graph.nodes == []

    # 2. Advisor builds in their own fork; the trunk stays untouched. A
    #    traveler content write on the trunk is refused with fork_required.
    with pytest.raises(ApiError) as exc:
        await traveler.add_node(trunk_id, type="experience", title="not allowed on trunk")
    assert exc.value.status == 409
    assert exc.value.detail == "fork_required"

    advisor_fork = await advisor.fork_itinerary(trunk_id, title="advisor workspace")
    advisor_fork_id = str(advisor_fork.itinerary.id)
    assert str(advisor_fork.itinerary.forked_from_id) == trunk_id

    kaiseki = await advisor.add_node(
        advisor_fork_id, type="experience", title="Sunset kaiseki dinner"
    )
    await advisor.add_node(advisor_fork_id, type="hotel", title="Ryokan with a view")
    # An annotation card — must never participate in approval counts.
    await advisor.add_node(
        advisor_fork_id,
        type="note",
        title="Packing note",
        starts_at="2027-05-03T09:00:00+09:00",
    )
    assert (await advisor.get_graph(trunk_id)).nodes == []  # still private

    # 3. Publish: reconcile the advisor fork into the trunk, accepting all.
    published = await advisor.reconcile_fork(advisor_fork_id, accept_all=True)
    assert str(published.fork.fork_status) == "reconciled"
    trunk_graph = await advisor.get_graph(trunk_id)
    assert str(trunk_graph.itinerary.display_status) == "with_traveler"
    titles = {n.title for n in trunk_graph.nodes}
    assert {"Sunset kaiseki dinner", "Ryokan with a view", "Packing note"} <= titles
    assert all(str(n.status) == "pending" for n in trunk_graph.nodes)
    assert_no_violations(graph_integrity(trunk_graph))

    # 4. The linked traveler can read the trunk but not content-edit it; they
    #    fork their own working copy and edit there.
    traveler_view = await traveler.get_graph(trunk_id)
    assert {n.title for n in traveler_view.nodes} == titles
    with pytest.raises(ApiError) as exc2:
        await traveler.add_node(trunk_id, type="meal", title="street food crawl")
    assert exc2.value.status == 409
    assert exc2.value.detail == "fork_required"

    traveler_fork = await traveler.fork_itinerary(trunk_id, title="my version")
    traveler_fork_id = str(traveler_fork.itinerary.id)
    assert_no_violations(fork_lineage_holds(traveler_fork, trunk_graph))
    await traveler.add_node(traveler_fork_id, type="meal", title="Street food crawl")

    # 5. Traveler asks staff to merge; advisor diffs + reconciles accept-all.
    await traveler.request_reconcile(traveler_fork_id, note="added a food night")
    diff = await advisor.fork_diff(traveler_fork_id)
    assert any(c.after and c.after.get("title") == "Street food crawl" for c in diff.added)
    merged = await advisor.reconcile_fork(traveler_fork_id, accept_all=True)
    assert str(merged.fork.fork_status) == "reconciled"
    assert merged.fork.reconcile_requested_at is None

    trunk_graph = await advisor.get_graph(trunk_id)
    assert "Street food crawl" in {n.title for n in trunk_graph.nodes}

    # 6. Traveler approves one card, then approve-all sweeps the rest. The
    #    note stays pending (non-approvable) without holding the bucket back.
    kaiseki_on_trunk = next(
        n for n in trunk_graph.nodes if n.title == "Sunset kaiseki dinner"
    )
    approved_one = await traveler.update_node(
        trunk_id, str(kaiseki_on_trunk.id), fields={"status": "approved"}
    )
    assert str(approved_one.status) == "approved"

    # approve-all is meaningless on a fork — the API says so.
    with pytest.raises(ApiError) as exc3:
        await traveler.approve_all(traveler_fork_id)
    assert exc3.value.status == 409
    assert exc3.value.detail == "not_a_trunk"

    result = await traveler.approve_all(trunk_id)
    assert result.approved_count >= 2  # hotel + meal (kaiseki already approved)
    final = result.graph
    assert str(final.itinerary.display_status) == "approved"
    by_title = {n.title: str(n.status) for n in final.nodes}
    assert by_title["Sunset kaiseki dinner"] == "approved"
    assert by_title["Ryokan with a view"] == "approved"
    assert by_title["Street food crawl"] == "approved"
    assert by_title["Packing note"] == "pending"  # annotation kinds never approve

    # Idempotent: a second sweep finds nothing pending-approvable.
    again = await traveler.approve_all(trunk_id)
    assert again.approved_count == 0
