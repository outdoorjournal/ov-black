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

import flows
import pytest

pytestmark = pytest.mark.e2e


async def test_booked_node_is_immutable_to_traveler_and_agent() -> None:
    """G1 — status-aware mutation gate: booked/confirmed nodes are immutable.

    `ovb.invariants.status_actor_gate_holds` raises `NotImplementedError` today;
    it becomes the assertion here when `services/itineraries._check_status_gate`
    lands. Intended flow (M004/G1):

        # status × actor matrix — every cell asserted:
        #   idea/proposed     → editable by traveler, agent, advisor
        #   approved          → advisor-only (after demote); traveler/agent refused
        #   booked/confirmed  → immutable; only advisor demotion/cancellation moves it
        for status in ("booked", "confirmed"):
            node = await advisor.set_node_status(itin, node_id, status)
            with pytest.raises(ApiError) as exc:
                await traveler.update_node(itin, node_id, fields={"title": "changed"})
            assert exc.value.status == 409                  # crafted refusal, not a 500
            assert "booked" in exc.value.reason or node.lock_reason

        # advisor demotion succeeds and writes a visible node_history note.
        await advisor.demote_node(itin, node_id, reason="supplier cancelled")
        assert_no_violations(status_actor_gate_holds(<graph>, <actor matrix>))
    """
    flows.skip_until("M004/G1", "status-aware mutation gates (booked/confirmed immutability)")


async def test_traveler_forks_an_approved_itinerary() -> None:
    """G2 — versioned-clone fork (D-FORK): pre-booked copies editable, booked carried locked.

    Intended flow (M004/G2):

        # 1. Start from an approved itinerary with a mix of statuses (incl. one booked).
        fork = await traveler.fork_itinerary(itin)          # agent tool / traveler-initiated
        assert fork.forked_from_id == itin

        # 2. Pre-booked nodes copy in editable; booked/confirmed copy in LOCKED.
        fg = await traveler.get_graph(fork.id)
        assert all(n.forked_from_node_id for n in fg.nodes)  # lineage on every node
        booked = [n for n in fg.nodes if str(n.status) in {"booked", "confirmed"}]
        assert booked and all(n.locked for n in booked)

        # 3. The fork mutates independently of the baseline (AI rewrites a day).
        await traveler.update_node(fork.id, some_prebooked_node, fields={"title": "..."})
        assert (await traveler.get_graph(itin))  # baseline unchanged
    """
    flows.skip_until("M004/G2", "itinerary fork (versioned clone + lineage)")


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
