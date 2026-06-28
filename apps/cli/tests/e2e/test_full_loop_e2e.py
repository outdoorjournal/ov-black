"""The concierge-to-confirmed loop, end-to-end (mvp.md §7 demo script).

This is the integration *spine*: where the per-pillar files prove each capability
in isolation, this chains them on a single client and walks the *whole* loop —
invite → dream → build → approve → detail → fork/reconcile → invoice/book/confirm.

    1 INVITE → 2 DREAM → 3 BUILD → 4 DETAIL → 5 FORK/RECONCILE → 6 INVOICE/BOOK
    └──── front+middle (this file, part 1) ────┘└──── back half (part 2) ────┘

Stages 1–3 live in ``test_loop_invite_to_approved``; the back half (4–6) is
``test_loop_detail_to_confirmed_continuation`` — both halves now exercise built
backend (M003/M004/M005 have landed). The continuation needs a linked traveler
whose client the advisor owns (so the advisor builds + reconciles + invoices while
the traveler details, forks, and pays), so it self-skips where that identity is
not provisioned on the box.

Run it against the local mock for a fast, deterministic spine, or against real
Bedrock + live vendors for the founder craft-feel UAT (F3). It asserts on
invariants, so it is green either way; only the *richness* (real cards, grown
profile, four vendors) differs. The paid-dependent tail self-skips where no
payment gateway is wired.
"""

from __future__ import annotations

import contextlib
from datetime import date, timedelta
from decimal import Decimal

import flows
import pytest

from ovb.agent import Conversation
from ovb.errors import ApiError
from ovb.invariants import (
    assert_no_violations,
    cost_totals,
    fork_lineage_holds,
    graph_integrity,
    money_gate_reconciles,
    reconcile_holds,
)
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_loop_invite_to_approved(advisor: Ovb, harness: Harness) -> None:
    """Stages 1–3: a client is invited, dreams, an itinerary is built and approved."""
    # ── Stage 1 · INVITE ─────────────────────────────────────────────────────
    client_id, _email = await flows.ensure_client(
        advisor,
        full_name="Loop Subject",
        net_worth=400_000_000,
        party_notes="Anniversary trip; she's vegetarian; no early mornings.",
    )
    await flows.seed_dossier(
        advisor,
        client_id,
        dossier=[("preference", "Hates being rushed; values privacy above all.")],
        profile=[("dream_signal", "Mentioned wanting to see autumn leaves in Japan.")],
    )
    detail = await advisor.get_client(client_id)
    assert str(detail.access_status) == "pending"
    harness.client_id = client_id
    harness.record("invited", client_id=client_id)

    # ── Stage 2 · DREAM ──────────────────────────────────────────────────────
    convo = await Conversation.open(advisor, client_id=client_id)
    before = len(await advisor.list_turns(convo.session_id))
    turn = await convo.say("We loved the idea of Japan in autumn. Where would you start us?")
    assert turn.done is not None or turn.error is not None
    assert len(await advisor.list_turns(convo.session_id)) >= before + 1
    if convo.itinerary_id:
        assert_no_violations(graph_integrity(await advisor.get_graph(convo.itinerary_id)))
    harness.record("dreamed", session_id=convo.session_id)

    # ── Stage 3 · BUILD ──────────────────────────────────────────────────────
    # Assemble a concrete, multi-day itinerary from the seed deck (deterministic,
    # agent-independent) so the build/analyze/fill spine is exercised every run.
    itinerary_id = await flows.ensure_japan_itinerary(advisor, client_id=client_id)
    harness.itinerary_id = itinerary_id

    # 3a. Drop a real inventory card on it; provenance + cost ride along.
    found = await flows.search_inventory(advisor, kind="experience", keyword="Como")
    node = await flows.propose_addable(advisor, itinerary_id, found.items)
    if node is not None:
        assert_no_violations(flows.assert_provenance(node))
        harness.record("card_added", node_id=str(node.id), source=node.source)

    # 3b. Analyze for feasibility — the async state machine must terminate cleanly.
    analysis = await flows.analyze_and_wait(harness, advisor, itinerary_id, depth="standard")
    assert str(analysis.status) == "completed", analysis.error_detail

    # 3c. Fill an open window, if the graph has one and a provider can serve it.
    gap = flows.find_fill_gap(await advisor.get_graph(itinerary_id))
    if gap is not None:
        fill = await advisor.fill(itinerary_id, gap_start=gap.start, gap_end=gap.end, min_score=0.0)
        for p in fill.proposals:
            assert p.inventory_source and p.inventory_id
            assert p.fits_in_gap or p.feasibility_unknown
        harness.record("filled", proposals=len(fill.proposals))

    # 3d. Approve → the itinerary becomes client-visible.
    with contextlib.suppress(Exception):  # lock is best-effort; approve is the assertion.
        await advisor.lock(itinerary_id)
    approved = await advisor.approve(itinerary_id)
    assert str(approved.status) == "approved"

    # The cost spine (B4) yields a real per-currency total — the money gate's input.
    graph = await advisor.get_graph(itinerary_id)
    assert str(graph.itinerary.status) == "approved"
    assert_no_violations(graph_integrity(graph))
    cost_totals(graph)  # computable without raising; values asserted in Pillar 3.
    harness.record("approved", itinerary_id=itinerary_id)


async def test_loop_client_sees_approved_itinerary(
    advisor: Ovb, traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """Stage 3 hand-off: the traveler sees an approved itinerary on their own surface.

    Needs a linked traveler whose client the advisor owns (so the advisor can build
    + approve, and the traveler can read it back via `GET /me/itineraries`).
    """
    client_id = linked_traveler_client_id
    try:
        await advisor.get_client(client_id)
    except Exception:  # noqa: BLE001
        pytest.skip("advisor does not own the linked traveler's client")

    # Build + approve as advisor, then assert the traveler can see it.
    itinerary_id = await flows.ensure_japan_itinerary(advisor, client_id=client_id)
    with contextlib.suppress(Exception):
        await advisor.lock(itinerary_id)
    await advisor.approve(itinerary_id)

    mine = await traveler.my_itineraries()
    ids = {str(s.id) for s in mine.itineraries}
    assert itinerary_id in ids, "approved itinerary not visible on the traveler's surface"
    approved_here = next(s for s in mine.itineraries if str(s.id) == itinerary_id)
    assert str(approved_here.status) == "approved"


async def test_loop_detail_to_confirmed_continuation(
    advisor: Ovb,
    traveler: Ovb,
    linked_traveler_client_id: str,
    harness: Harness,
) -> None:
    """Stages 4–6: the back half of the loop, chained on one linked-traveler client.

    Where the per-pillar files prove each capability in isolation, this walks the
    continuation as a single narrative across two real JWTs (advisor + traveler):

        4 DETAIL  (M003) — the traveler adds a party member + uploads a passport to
                  the vault; the advisor sees both, and the member rides onto the trip.
        5 FORK    (M004) — the traveler forks the approved trip, reworks the
                  alternative, and *requests* a merge (but can't execute it); the
                  advisor diffs, feasibility-checks, and reconciles the accepted change.
        6 INVOICE (M005) — the advisor prices + invoices a bookable node; the traveler
                  pays (Braintree sandbox); the money gate lets it book; a supplier
                  confirmation advances it to confirmed; the reconciliation invariant
                  (Σ paid lines ⇔ Σ booked node costs) holds.

    Builds a *fresh* itinerary (not the idempotent demo) so the diff and the booking
    are clean on every run against a persistent stack. Asserts on invariants only, so
    it is green against the local mock and real Bedrock/vendors alike.
    """
    client_id = linked_traveler_client_id
    # The advisor must own the linked traveler's client to build/reconcile/invoice on it.
    try:
        await advisor.get_client(client_id)
    except ApiError:
        pytest.skip("advisor does not own the linked traveler's client")

    # A fresh, isolated trip for this loop run (re-runnable; not the shared demo).
    itin = await advisor.create_itinerary(title="Loop continuation trip", client_id=client_id)
    itinerary_id = str(itin.id)
    plan_node = await advisor.add_node(
        itinerary_id, type="experience", title="Kyoto temple morning", status="proposed"
    )
    harness.itinerary_id = itinerary_id

    # ── Stage 4 · DETAIL ─────────────────────────────────────────────────────
    # The traveler maintains their own household and uploads a passport; the
    # advisor sees both, and the member is attached to the trip.
    member = await traveler.create_my_party_member(
        {"full_name": "Loop Companion", "dietary": "vegetarian"}
    )
    member_id = str(member.id)
    assert str(member.created_by_actor) == "traveler"

    soon = (date.today() + timedelta(days=30)).isoformat()
    init = await traveler.init_my_document(
        {
            "doc_type": "passport",
            "file_name": "passport.pdf",
            "content_type": "application/pdf",
            "label": "Loop passport",
            "party_member_id": member_id,
            "expires_at": soon,
        }
    )
    doc_id = str(init.document.id)
    await traveler.complete_my_document(doc_id, size_bytes=2048)

    # The advisor sees the traveler-entered member and the uploaded document.
    advisor_party = await advisor.list_party_members(client_id)
    assert member_id in {str(m.id) for m in advisor_party.members}
    advisor_docs = await advisor.list_client_documents(client_id)
    assert doc_id in {str(d.id) for d in advisor_docs.documents}

    attached = await advisor.attach_party_member(itinerary_id, member_id)
    assert member_id in {str(e.party_member_id) for e in attached.members}
    harness.record("detailed", member_id=member_id, document_id=doc_id)

    # ── Stage 5 · FORK / RECONCILE ───────────────────────────────────────────
    # Approve the baseline, then the traveler forks it and reworks the alternative.
    with contextlib.suppress(Exception):  # lock is best-effort; approve is the gate.
        await advisor.lock(itinerary_id)
    await advisor.approve(itinerary_id)
    baseline_before = await advisor.get_graph(itinerary_id)
    assert str(baseline_before.itinerary.status) == "approved"
    assert_no_violations(graph_integrity(baseline_before))

    fork = await traveler.fork_itinerary(itinerary_id)
    fork_id = str(fork.itinerary.id)
    assert str(fork.itinerary.forked_from_id) == itinerary_id
    assert_no_violations(fork_lineage_holds(fork, baseline_before))

    fork_node = next(n for n in fork.nodes if str(n.forked_from_node_id) == str(plan_node.id))
    await traveler.update_node(fork_id, str(fork_node.id), fields={"title": "Slower Kyoto morning"})

    # The traveler can *request* a merge but not execute one (advisor-only).
    requested = await traveler.request_reconcile(fork_id, note="prefer the slower version")
    assert requested.reconcile_requested_at is not None
    with pytest.raises(ApiError) as exc:
        await traveler.reconcile_fork(fork_id, decisions=[])
    assert exc.value.status == 403

    # The advisor diffs, feasibility-checks, and reconciles the accepted change.
    diff = await advisor.fork_diff(fork_id)
    change = next(c for c in diff.changed if str(c.baseline_node_id) == str(plan_node.id))
    analysis = await flows.analyze_and_wait(harness, advisor, fork_id)
    assert str(analysis.status) == "completed", analysis.error_detail
    result = await advisor.reconcile_fork(
        fork_id,
        decisions=[{"change_id": str(change.change_id), "accept": True}],
        analysis_id=str(analysis.id),
    )
    assert result.outcomes[0].result == "applied"
    assert str(result.fork.fork_status) == "reconciled"

    live = await advisor.get_graph(itinerary_id)
    live_title = next(n.title for n in live.nodes if str(n.id) == str(plan_node.id))
    assert live_title == "Slower Kyoto morning"
    assert_no_violations(reconcile_holds(live, [change], baseline_before))
    harness.record("reconciled", fork_id=fork_id)

    # ── Stage 6 · INVOICE / BOOK / CONFIRM ───────────────────────────────────
    # A fresh, priced, approved bookable node (fresh ⇒ never already-booked across
    # re-runs); the advisor invoices it, the traveler pays, the money gate lets it
    # book, a supplier confirmation confirms it, and reconciliation balances.
    bookable = await advisor.add_node(
        itinerary_id,
        type="experience",
        title="Private kaiseki dinner",
        status="proposed",
        cost_amount="1000.00",
        cost_currency="USD",
        cost_kind="total",
    )
    node_id = str(bookable.id)
    await advisor.update_node(itinerary_id, node_id, fields={"status": "approved"})

    invoice = await advisor.create_invoice(itinerary_id, label="Deposit", currency="USD")
    charge = await advisor.add_invoice_line(str(invoice.id), node_id=node_id)
    assert Decimal(str(charge.amount)) == Decimal("1000.00")
    await advisor.issue_invoice(str(invoice.id))

    # The traveler pays their own invoice (owning client). Self-skip where unwired.
    try:
        paid = await traveler.pay_invoice(str(invoice.id), payment_method_nonce="fake-valid-nonce")
    except ApiError as pay_exc:
        if pay_exc.detail == "payments_unconfigured":
            pytest.skip("no payment gateway wired on this target (prod without keys)")
        raise
    assert str(paid.status) == "paid"
    harness.record("paid", invoice_id=str(invoice.id))

    # An unpaid node is gated; this one is covered, so it books and then confirms.
    booking = await advisor.book_node(itinerary_id, node_id)
    assert str(booking.node_status) == "booked"
    confirmed = await advisor.record_confirmation(itinerary_id, node_id, supplier_ref="LOOP-001")
    assert str(confirmed.node_status) == "confirmed"

    # The loop closes: Σ(paid invoice lines) ⇔ Σ(booked node costs).
    report = await advisor.get_reconciliation(itinerary_id)
    assert_no_violations(money_gate_reconciles(report))
    assert report.balanced is True
    harness.record("confirmed", node_id=node_id)
