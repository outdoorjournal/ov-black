"""Pillar 5 — Traveler forks with AI; staff reconcile; booked nodes are immutable.

Demo-script stage 5 (mvp.md §7): *"Traveler asks AI for an alternate version; a
fork is created and mutated; advisor opens the diff, checks feasibility, and
reconciles selected changes into the live plan. A booked node refuses edits."*

Acceptance (mvp.md Pillar 5):
  - A traveler (via the agent) forks an approved itinerary; AI mutates the fork.
  - Staff get a diff (added/removed/changed/moved), side by side.
  - Staff reconcile: accept/discard individual changes after an Analyze check.
  - A booked/confirmed node is immutable — edits by traveler/agent refused with a
    crafted explanation; only an advisor moves it, via explicit demotion.

Status: 🔨 NOT BUILT (M004). No fork/version concept, no diff/reconcile surface;
status-aware mutation gates are design-only — today a booked node can be retitled
by anyone holding the editor lock. These scaffolds `skip_until` the slice that
lands each piece; the immutability test is wired to `ovb.invariants`' honest stub
so it lights up the moment G1 ships.
"""

from __future__ import annotations

from typing import Any

import flows
import pytest

from ovb.errors import ApiError
from ovb.invariants import (
    assert_no_violations,
    fork_lineage_holds,
    status_actor_gate_holds,
)
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


def _editable_bookable(graph: Any) -> Any | None:
    """First currently-editable bookable node (a candidate to book then lock)."""
    bookable = {"flight", "hotel", "experience", "meal"}
    editable = {"idea", "proposed", "approved"}
    return next(
        (n for n in graph.nodes if str(n.type) in bookable and str(n.status) in editable),
        None,
    )


async def test_booked_node_is_immutable_to_traveler_and_agent(
    advisor: Ovb, traveler: Ovb, built_itinerary: str
) -> None:
    """G1 — status-aware mutation gate: booked nodes are immutable to non-advisors.

    Drives the whole status×actor contract over the wire with two real JWTs (the
    traveler is the same non-advisor path the agent uses): advisor books a node →
    a traveler edit is refused 409 → an advisor field-edit is refused until they
    demote → demotion (a pure status change) reopens it. The static lock_reason
    half is asserted with ``status_actor_gate_holds``.
    """
    itin = built_itinerary
    graph = await advisor.get_graph(itin)
    node = _editable_bookable(graph)
    if node is None:
        pytest.skip("no editable bookable node in the seeded itinerary to book")
    node_id = str(node.id)

    # Advisor books the node (proposed→booked is an ungated promotion in G1).
    booked = await advisor.update_node(itin, node_id, fields={"status": "booked"})
    assert str(booked.status) == "booked"
    assert booked.lock_reason == "status_locked"

    # Static contract: every firmed node advertises its lock_reason, no others do.
    assert_no_violations(status_actor_gate_holds(await advisor.get_graph(itin)))

    # A traveler (the agent's non-advisor path) is refused with a crafted 409.
    with pytest.raises(ApiError) as exc:
        await traveler.update_node(itin, node_id, fields={"title": "changed by traveler"})
    assert exc.value.status == 409
    assert exc.value.detail == "status_locked"

    # Even an advisor must demote first — a field edit on a booked node is refused.
    with pytest.raises(ApiError) as exc2:
        await advisor.update_node(itin, node_id, fields={"title": "renamed without demoting"})
    assert exc2.value.status == 409
    assert exc2.value.detail == "demote_before_edit"

    # Advisor demotion (a pure status change) succeeds and reopens the node.
    demoted = await advisor.update_node(itin, node_id, fields={"status": "proposed"})
    assert str(demoted.status) == "proposed"
    edited = await advisor.update_node(itin, node_id, fields={"title": "now editable again"})
    assert edited.title == "now editable again"


async def test_traveler_forks_an_approved_itinerary(
    advisor: Ovb, traveler: Ovb, built_itinerary: str
) -> None:
    """G2 — versioned-clone fork (D-FORK): pre-booked copies editable, booked carried locked.

    The owner forks an approved itinerary that has a booked node; the fork is a
    faithful clone (lineage on every node, the booking carried locked, a different
    itinerary) and is independently editable. A non-owner traveler can't fork it.
    """
    itin = built_itinerary
    graph = await advisor.get_graph(itin)
    node = _editable_bookable(graph)
    if node is None:
        pytest.skip("no editable bookable node to book before forking")

    # An approved itinerary carrying a booked node (the "can't fork away a booking" case).
    await advisor.update_node(itin, str(node.id), fields={"status": "booked"})
    await advisor.approve(itin)
    baseline = await advisor.get_graph(itin)

    # A non-owner traveler cannot fork someone else's itinerary.
    with pytest.raises(ApiError) as exc:
        await traveler.fork_itinerary(itin)
    assert exc.value.status in (403, 404)

    # The owner forks it; the fork is a faithful versioned clone.
    fork = await advisor.fork_itinerary(itin)
    assert str(fork.itinerary.forked_from_id) == itin
    assert str(fork.itinerary.fork_status) == "open"
    assert str(fork.itinerary.id) != itin
    assert_no_violations(fork_lineage_holds(fork, baseline))

    # The carried booking is present and locked in the fork.
    carried = [n for n in fork.nodes if str(n.status) == "booked"]
    assert carried and all(n.lock_reason == "status_locked" for n in carried)

    # The fork edits independently of the baseline: rework a pre-booked fork node,
    # the baseline node keeps its title.
    prebooked = next(n for n in fork.nodes if str(n.status) != "booked")
    origin_id = str(prebooked.forked_from_node_id)
    baseline_title = next(n.title for n in baseline.nodes if str(n.id) == origin_id)
    await advisor.update_node(
        str(fork.itinerary.id), str(prebooked.id), fields={"title": "reworked in the fork"}
    )
    after = await advisor.get_graph(itin)
    assert next(n.title for n in after.nodes if str(n.id) == origin_id) == baseline_title


async def test_advisor_diffs_and_reconciles_a_fork() -> None:
    """G3 — diff + reconcile: accept a subset into the live plan after an Analyze check.

    Intended flow (M004/G3):

        # 1. Diff the fork against its baseline by lineage pairing.
        diff = await advisor.diff_fork(fork.id)             # added/removed/changed/moved
        assert diff.added or diff.changed

        # 2. Feasibility-gate before accepting (reuse B5 Analyze on the fork).
        analysis = await flows.analyze_and_wait(harness, advisor, fork.id)
        assert str(analysis.status) == "completed"

        # 3. Accept a subset → mutates the LIVE graph through the same lock/queue path.
        await advisor.reconcile(fork.id, accept=[change_a.id], discard=[change_b.id])
        live = await advisor.get_graph(itin)
        assert change_a applied and change_b absent

        # 4. A booked node cannot be changed via reconcile (gate from G1 still holds).
    """
    flows.skip_until("M004/G3", "fork diff + reconcile surface")
