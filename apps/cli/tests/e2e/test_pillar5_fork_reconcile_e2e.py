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

Status: ✅ BUILT (M004 + the M005 money gate). Fork/version, diff/reconcile, and the
status×actor mutation gates have landed. Booking is now exclusively the money gate's
job (M005): a node reaches ``booked`` only through a paid invoice, so these tests
book via ``flows.book_node_via_money_gate`` and assert that a *direct* status flip is
refused. They self-skip only where the traveler identity or a payment gateway isn't
wired on the box.
"""

from __future__ import annotations

from typing import Any

import flows
import pytest

from ovb.errors import ApiError
from ovb.invariants import (
    BOOKABLE_TYPES,
    assert_no_violations,
    fork_lineage_holds,
    reconcile_holds,
    status_actor_gate_holds,
)
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


def _editable_bookable(graph: Any) -> Any | None:
    """First currently-editable bookable node (a candidate to book then lock).

    Excludes ``flight``: since the fresh-offer money gate, booking a flight
    additionally requires a non-expired ``NodeOffer`` (``offer_required``) that
    ``book_node_via_money_gate`` doesn't mint — flights book off a re-priced
    offer, a separate flow. Any static-cost bookable (hotel/experience/meal)
    proves the same G1 status×actor lock this test asserts.
    """
    bookable = {"hotel", "experience", "meal"}
    editable = {"pending", "approved"}
    return next(
        (n for n in graph.nodes if str(n.type) in bookable and str(n.status) in editable),
        None,
    )


async def test_booked_node_is_immutable_to_traveler_and_agent(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """G1 — status-aware mutation gate: booked nodes are immutable to non-advisors.

    Drives the status×actor contract over the wire with two real JWTs (the
    traveler is the same non-advisor path the agent uses). Under the trunk
    model the traveler's refusals are layered: a content edit on the OFFICIAL
    trunk is refused by the trunk guard (``fork_required`` — fork first), and
    on their own fork the booked node carries LOCKED, so the edit is refused
    by G1 (``status_locked``). The advisor keeps the demote-before-edit
    escape hatch on the trunk. The static lock_reason half is asserted with
    ``status_actor_gate_holds``.
    """
    itin = await flows.ensure_japan_itinerary(advisor, client_id=linked_traveler_client_id)
    graph = await advisor.get_graph(itin)
    node = _editable_bookable(graph)
    if node is None:
        pytest.skip("no editable bookable node in the seeded itinerary to book")
    node_id = str(node.id)

    # Advisor books the node through the money gate (since M005 the only path to
    # ``booked`` — a direct update_node status flip is refused, asserted below).
    await flows.book_node_via_money_gate(advisor, itin, node_id)
    booked = next(n for n in (await advisor.get_graph(itin)).nodes if str(n.id) == node_id)
    assert str(booked.status) == "booked"
    assert booked.lock_reason == "status_locked"

    # Static contract: every firmed node advertises its lock_reason, no others do.
    assert_no_violations(status_actor_gate_holds(await advisor.get_graph(itin)))

    # Layer 1 — the trunk guard: a traveler content edit on the official trunk
    # is refused outright; content reaches the trunk only via publish.
    with pytest.raises(ApiError) as exc:
        await traveler.update_node(itin, node_id, fields={"title": "changed by traveler"})
    assert exc.value.status == 409
    assert exc.value.detail == "fork_required"

    # Layer 2 — G1 in the working copy: the booked node carries locked into the
    # traveler's fork, so even there the edit is refused with the crafted 409.
    fork = await traveler.fork_itinerary(itin)
    fork_id = str(fork.itinerary.id)
    fork_node = next(n for n in fork.nodes if str(n.forked_from_node_id) == node_id)
    assert str(fork_node.status) == "booked"  # carried locked
    with pytest.raises(ApiError) as exc_fork:
        await traveler.update_node(
            fork_id, str(fork_node.id), fields={"title": "changed in my version"}
        )
    assert exc_fork.value.status == 409
    assert exc_fork.value.detail == "status_locked"

    # Even an advisor must demote first — a field edit on a booked node is refused.
    with pytest.raises(ApiError) as exc2:
        await advisor.update_node(itin, node_id, fields={"title": "renamed without demoting"})
    assert exc2.value.status == 409
    assert exc2.value.detail == "demote_before_edit"

    # Advisor demotion (a pure status change) succeeds and reopens the node.
    demoted = await advisor.update_node(itin, node_id, fields={"status": "pending"})
    assert str(demoted.status) == "pending"
    edited = await advisor.update_node(itin, node_id, fields={"title": "now editable again"})
    assert edited.title == "now editable again"


async def test_direct_booked_flip_is_refused_use_booking_flow(
    advisor: Ovb, built_itinerary: str
) -> None:
    """The money gate (M005) can't be bypassed: a direct flip to booked is a clean 409.

    Booking authority is the money gate (a covering paid invoice line); a straight
    ``update_node(status='booked')`` must be refused with ``409 use_booking_flow`` —
    never a 500 (regression: ``CONFLICT`` was unmapped in the itinerary router).
    """
    node = _editable_bookable(await advisor.get_graph(built_itinerary))
    if node is None:
        pytest.skip("no editable bookable node to attempt a direct booking on")

    with pytest.raises(ApiError) as exc:
        await advisor.update_node(built_itinerary, str(node.id), fields={"status": "booked"})
    assert exc.value.status == 409, exc.value
    assert exc.value.detail == "use_booking_flow"


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
    await flows.book_node_via_money_gate(advisor, itin, str(node.id))
    await advisor.approve_all(itin)
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


async def test_advisor_diffs_and_reconciles_a_fork(
    advisor: Ovb, harness: Any, built_itinerary: str
) -> None:
    """G3 — diff + reconcile: accept a subset into the live plan after an Analyze check.

    Books a node (so the fork carries a locked booking reconcile must never touch),
    forks, reworks a pre-booked node + adds one, diffs by lineage, runs Analyze on
    the fork, then accepts the rework and discards the add — and asserts the live
    baseline reflects only the accepted change while the booking is untouched.
    """
    itin = built_itinerary
    graph = await advisor.get_graph(itin)

    # Book a node so the fork carries a locked booking.
    bookable = _editable_bookable(graph)
    if bookable is None:
        pytest.skip("no editable bookable node to book before forking")
    await flows.book_node_via_money_gate(advisor, itin, str(bookable.id))
    await advisor.approve_all(itin)

    fork = await advisor.fork_itinerary(itin)
    fork_id = str(fork.itinerary.id)

    # Rework a pre-booked content node (→ changed) and add a node (→ added).
    prebooked = next(
        n for n in fork.nodes if str(n.status) == "pending" and str(n.type) in BOOKABLE_TYPES
    )
    origin_id = str(prebooked.forked_from_node_id)
    await advisor.update_node(fork_id, str(prebooked.id), fields={"title": "Slower Kyoto morning"})
    added = await advisor.add_node(
        fork_id, type="experience", title="Tea ceremony", status="pending"
    )

    diff = await advisor.fork_diff(fork_id)
    change_keep = next(c for c in diff.changed if str(c.baseline_node_id) == origin_id)
    change_drop = next(c for c in diff.added if str(c.fork_node_id) == str(added.id))

    # Feasibility-gate on the fork (it carries geo from G2, so standard Analyze runs).
    analysis = await flows.analyze_and_wait(harness, advisor, fork_id)
    assert str(analysis.status) == "completed"

    baseline_before = await advisor.get_graph(itin)
    result = await advisor.reconcile_fork(
        fork_id,
        decisions=[
            {"change_id": str(change_keep.change_id), "accept": True},
            {"change_id": str(change_drop.change_id), "accept": False},
        ],
        analysis_id=str(analysis.id),
    )
    outcomes = {str(o.change_id): str(o.result) for o in result.outcomes}
    assert outcomes[str(change_keep.change_id)] == "applied"
    assert outcomes[str(change_drop.change_id)] == "discarded"

    # The live baseline reflects only the accepted change; the discarded add is absent.
    live = await advisor.get_graph(itin)
    assert next(n.title for n in live.nodes if str(n.id) == origin_id) == "Slower Kyoto morning"
    assert all(str(n.title) != "Tea ceremony" for n in live.nodes)
    # Invariant: accepted folded in, the carried booking never mutated.
    assert_no_violations(reconcile_holds(live, [change_keep], baseline_before))


async def test_traveler_requests_and_advisor_reconciles(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """G3 conversational fork — the traveler requests a merge; the advisor executes it.

    The traveler owns an itinerary (via their linked client), forks it, reworks the
    alternative, and *requests* reconciliation — but cannot execute it (403). The
    advisor sees the pending request, reconciles, and the live baseline reflects the
    merge while the request is cleared.
    """
    client_id = linked_traveler_client_id
    itin = await advisor.create_itinerary(title="Traveler trip", client_id=client_id)
    itin_id = str(itin.id)
    n1 = await advisor.add_node(
        itin_id, type="experience", title="Original plan", status="pending"
    )
    await advisor.approve_all(itin_id)

    # The traveler forks their own itinerary and reworks the alternative.
    fork = await traveler.fork_itinerary(itin_id)
    fork_id = str(fork.itinerary.id)
    fork_node = next(n for n in fork.nodes if str(n.forked_from_node_id) == str(n1.id))
    await traveler.update_node(
        fork_id, str(fork_node.id), fields={"title": "Traveler's alternative"}
    )

    # The traveler can REQUEST a merge but not execute one.
    requested = await traveler.request_reconcile(fork_id, note="prefer the slower version")
    assert requested.reconcile_requested_at is not None
    with pytest.raises(ApiError) as exc:
        await traveler.reconcile_fork(fork_id, decisions=[])
    assert exc.value.status == 403

    # The advisor sees the request and executes the reconcile.
    diff = await advisor.fork_diff(fork_id)
    change = next(c for c in diff.changed if str(c.baseline_node_id) == str(n1.id))
    result = await advisor.reconcile_fork(
        fork_id, decisions=[{"change_id": str(change.change_id), "accept": True}]
    )
    assert result.outcomes[0].result == "applied"
    assert str(result.fork.fork_status) == "reconciled"
    assert result.fork.reconcile_requested_at is None

    live = await advisor.get_graph(itin_id)
    assert next(n.title for n in live.nodes if str(n.id) == str(n1.id)) == "Traveler's alternative"
