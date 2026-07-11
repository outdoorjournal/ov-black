"""Olympus campaign demo — the deterministic scaffold, end-to-end (over the wire).

Demo-script (bugs.md §Demo Flow): an inbound-campaign CTA seeds a Mt Olympus
trip for Robin; the agent lays a length-snapped skeleton; a reading-list article
and a real airport transfer join the Collection; the advisor makes it official
and issues a payable invoice.

This test drives the *deterministic* half with the same SDK the UI uses — seed,
snap, spine, article, transfer, then fork → reconcile → invoice → pay — asserting
graph diffs + invariants, never wording. The conversational half (campaign-aware
intake, the agent choosing the tools on the dashboard kickoff) is covered by the
declarative live-agent eval in ``olympus_scenarios.json``.

Steps that need infra the target may lack self-skip rather than false-fail: the
transfer needs Google Routes creds; the pay step needs a payment gateway.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import flows
import pytest

from ovb.errors import ApiError
from ovb.invariants import assert_no_violations, graph_integrity
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e

_ARTICLE_URL = "https://www.climbing.com/places/climbing-mount-olympus-greece/"


def _nodes_of_type(graph: Any, node_type: str) -> list[Any]:
    return [n for n in graph.nodes if str(n.type) == node_type]


async def test_olympus_campaign_demo(advisor: Ovb, harness: Harness) -> None:
    # 1. Provision the subject + facts (independent of the hand-seeded real Robin).
    client_id, _email = await flows.ensure_client(
        advisor, full_name="Robin Thurston (e2e)", net_worth=250_000_000
    )
    await flows.seed_dossier(
        advisor,
        client_id,
        profile=[("passion", "Lifelong cyclist — races since the early 1980s.")],
        dossier=[("motivation", "Founder & CEO of Outside Inc.")],
        osint=[("press", "Serial entrepreneur across fitness + media.")],
    )
    harness.client_id = client_id

    # 2. Seed the campaign shell — stamped campaign_id + hero mood, NO spine yet.
    seed = await advisor.seed_campaign("olympus", client_id=client_id)
    itin = str(seed.itinerary_id)
    harness.itinerary_id = itin
    assert str(seed.campaign_id) == "olympus"
    assert str(seed.mood) == "olympus"

    graph0 = await advisor.get_graph(itin)
    assert str(graph0.itinerary.campaign_id) == "olympus"
    assert str(graph0.itinerary.mood) == "olympus"
    assert len(graph0.nodes) == 0, "no spine should exist before kickoff"

    # 3. The traveler settled on ~6 nights → kickoff snaps UP to the 7-night spine
    #    and lands it on the itinerary (deterministic; the agent narrates reason).
    await advisor.update_itinerary(itin, timing_kind="window", duration_nights=6)
    before = await harness.snapshot(advisor, itin)
    kick = await advisor.campaign_kickoff(itin)
    assert kick.requested_nights == 6
    assert kick.snapped_length == 7
    assert str(kick.reason).strip(), "a snapped length must carry a human reason"
    assert kick.node_count > 0
    after = await harness.snapshot(advisor, itin)
    diff = before.diff(after)
    assert len(diff.added_nodes) == kick.node_count
    assert_no_violations(graph_integrity(after.graph))

    # A second kickoff must NOT re-lay the spine (idempotent for the demo).
    graph_after = await advisor.get_graph(itin)
    hotels = _nodes_of_type(graph_after, "hotel")
    assert hotels, "the spine should include lodging"

    # 4. Reading list — an article card, non-schedulable, in the Collection.
    art = await advisor.save_article(itin, url=_ARTICLE_URL)
    assert str(art.type) == "article"
    assert art.schedulable is False
    assert art.starts_at is None
    graph_art = await advisor.get_graph(itin)
    articles = _nodes_of_type(graph_art, "article")
    assert len(articles) == 1
    assert articles[0].schedulable is False

    # 5. A real, tier-aware airport transfer (Google Routes). Self-skip if the
    #    target has no routing key wired.
    try:
        xfer = await advisor.add_transfer(
            itin,
            origin="Thessaloniki Airport, Greece",
            destination="Litochoro, Greece",
            party_size=2,
            service_class="chauffeur_black",
        )
    except ApiError as exc:
        if exc.status == 502:
            pytest.skip("routes_unconfigured — no Google Routes key on target")
        raise
    else:
        assert str(xfer.type) == "drive"
        assert xfer.schedulable is True
        assert (xfer.metadata or {}).get("service_class") == "chauffeur_black"

    # 6. Advisor makes it official + issues a payable invoice.
    approved = await advisor.approve_all(itin)
    assert str(approved.graph.itinerary.display_status) == "approved"

    invoice = await advisor.create_invoice(itin, label="Olympus deposit", currency="EUR")
    await advisor.add_invoice_line(
        str(invoice.id), amount="5000", currency="EUR", description="Trip deposit"
    )
    issued = await advisor.issue_invoice(str(invoice.id))
    assert str(issued.status) == "issued"

    try:
        paid = await advisor.pay_invoice(str(invoice.id), payment_method_nonce="fake-valid-nonce")
    except ApiError as exc:
        if exc.status in (409, 501) or "unconfigured" in str(exc):
            pytest.skip("payments_unconfigured — no gateway on target")
        raise
    else:
        assert str(paid.status) == "paid"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))
