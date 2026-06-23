"""The concierge-to-confirmed loop, end-to-end (mvp.md §7 demo script).

This is the integration *spine*: where the per-pillar files prove each capability
in isolation, this chains them on a single client and walks the loop as far as the
built backend allows — invite → dream → build → approve, today — then hands off to
the milestone-gated back half (detail → fork → invoice → book) as an honest
continuation.

    1 INVITE → 2 DREAM → 3 BUILD → 4 DETAIL → 5 FORK/RECONCILE → 6 INVOICE/BOOK
    └──────── built front+middle half ───────┘└──────── M003 / M004 / M005 ───────┘

Run it against the local mock for a fast, deterministic spine, or against real
Bedrock + live vendors for the founder craft-feel UAT (F3). It asserts on
invariants, so it is green either way; only the *richness* (real cards, grown
profile, four vendors) differs.
"""

from __future__ import annotations

import contextlib

import flows
import pytest

from ovb.agent import Conversation
from ovb.invariants import assert_no_violations, cost_totals, graph_integrity
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
    assert str(detail.invite_status) == "pending"
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


async def test_loop_detail_to_confirmed_continuation() -> None:
    """Stages 4–6: the back half of the loop — gated on M003/M004/M005.

    The continuation, asserted in detail in the per-pillar files, is:

        4 DETAIL  (M003) — traveler enters party members + uploads a passport to the
                  vault; advisor sees them.            → test_pillar4_details_vault_e2e
        5 FORK    (M004) — traveler forks; advisor diffs + reconciles; a booked node
                  refuses edits.                       → test_pillar5_fork_reconcile_e2e
        6 INVOICE (M005) — advisor issues deposit + balance invoices; traveler pays
                  (Braintree sandbox); paid → booked → confirmed; the reconciliation
                  invariant holds.                     → test_pillar6_invoice_book_e2e

    The loop is "done" (mvp.md §7) when this chains green against real vendors with a
    founder craft-feel sign-off.
    """
    flows.skip_until("M003 → M005", "back half of the loop (detail · fork · invoice · book)")
