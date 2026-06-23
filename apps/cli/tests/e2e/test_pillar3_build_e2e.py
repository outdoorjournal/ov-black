"""Pillar 3 — Staff build a delightful itinerary fast, from multiple real sources.

Demo-script stage 3 (mvp.md §7): *"Advisor + AI assemble a multi-day itinerary
pulling a flight (Duffel), hotel (Ratehawk), an OV experience, and a restaurant
(Google Places); AI Fill closes a gap; advisor approves; the client sees it."*

Acceptance (mvp.md Pillar 3):
  - `search_inventory` dispatches to live adapters; every inventory-sourced node
    carries source + source_id provenance, rendered with attribution.
  - An advisor can build in minutes: instantiate, drop in inventory cards, run
    AI Fill to populate gaps with physically-feasible options.
  - Server-side linearization drives every rendered surface.

Provider reality: the registry defaults to `ov,mock`; Duffel/Ratehawk/Places turn
on only where their keys are configured (B1–B3 resume hooks). So the multi-source
search test asserts on *whatever providers are live* and records which were dark,
rather than hard-requiring four vendors — those gate F2's live-vendor validation.
"""

from __future__ import annotations

import contextlib

import flows
import pytest

from ovb.agent import Conversation
from ovb.errors import ApiError
from ovb.invariants import assert_no_violations, cost_totals, graph_integrity
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e

# kind → the search params that exercise that provider lane.
_LANES: dict[str, dict[str, object]] = {
    "experience": {"kind": "experience", "keyword": "Kyoto"},
    "meal": {"kind": "meal", "keyword": "sushi", "near_lat": 35.6762, "near_lng": 139.6503},
    "hotel": {
        "kind": "hotel",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "checkin": "2026-09-01",
        "checkout": "2026-09-03",
    },
    "flight": {
        "kind": "flight",
        "origin": "LAX",
        "destination": "HND",
        "departure_date": "2026-09-01",
    },
}


async def test_search_inventory_returns_normalized_items(advisor: Ovb) -> None:
    """Across every provider lane, items come back normalized with provenance.

    Self-skips only if *no* provider in any lane is live (registry misconfigured);
    otherwise asserts shape on whatever returned and reports the dark lanes.
    """
    live: dict[str, int] = {}
    dark: list[str] = []
    for kind, params in _LANES.items():
        resp = await flows.search_inventory(advisor, **params)
        if not resp.items:
            dark.append(kind)
            continue
        live[kind] = resp.count
        for item in resp.items:
            # Every normalized item is addressable for `node_from_inventory`.
            assert item.source, f"{kind} item missing source"
            assert item.source_id, f"{kind} item missing source_id"
            assert item.title, f"{kind} item missing title"

    if not live:
        pytest.skip(f"no inventory provider returned items (all lanes dark: {dark})")
    # Surface coverage so a partial run reads honestly in -v output.
    print(f"live inventory lanes: {live}; dark (needs creds, F2): {dark}")


async def test_proposing_an_inventory_node_carries_provenance_and_cost(
    advisor: Ovb, built_itinerary: str
) -> None:
    """Drop a real inventory item onto the graph → a proposed node with provenance.

    This is the `POST /nodes/from-inventory` seam the agent and the advisor
    authoring surface (B7) both use; cost (B4) is promoted from the item price.
    """
    # 1. Find real experiences to propose (OV/mock always cover this lane).
    found = await flows.search_inventory(advisor, kind="experience", keyword="Como")
    if not found.items:
        pytest.skip("no experience inventory available to propose")

    # 2. Propose the first detail-addressable item — lands as a `proposed` node.
    node = await flows.propose_addable(advisor, built_itinerary, found.items)
    if node is None:
        pytest.skip("no searched experience was detail-addressable for proposal")
    assert node is not None  # narrowed by the skip above (pytest.skip is NoReturn)
    assert str(node.status) == "proposed"
    assert_no_violations(flows.assert_provenance(node))

    # 3. Cost is both-or-neither: if the source priced it, the node carries numeric cost.
    if node.cost_amount is not None:
        assert node.cost_currency

    # 4. The graph stays structurally sound after the mutation.
    assert_no_violations(graph_integrity(await advisor.get_graph(built_itinerary)))


async def test_cost_rolls_up_per_currency(advisor: Ovb, built_itinerary: str) -> None:
    """Σ node cost per currency is computable — the input the M005 money gate needs.

    Mirrors `services/node_cost.sum_node_costs`; proves the B4 cost spine produces
    a real per-currency total over a built itinerary.
    """
    # Ensure the graph has at least one priced bookable: a priced inventory item
    # promotes its cost onto the node via `from-inventory` (B4 population). Filter to
    # items that actually carry a price (a search can also return priceless
    # destinations), so the proposed node is one the cost spine populates.
    found = await flows.search_inventory(advisor, kind="experience", keyword="Como")
    priced_items = [i for i in found.items if getattr(i, "price", None) is not None]
    await flows.propose_addable(advisor, built_itinerary, priced_items or found.items)

    graph = await advisor.get_graph(built_itinerary)
    priced = [n for n in graph.nodes if n.cost_amount is not None]
    if not priced:
        pytest.skip("no priced inventory available to total (all provider lanes priceless)")

    totals = cost_totals(graph)
    assert totals, "priced nodes exist but produced no currency totals"
    assert all(amount > 0 for amount in totals.values())


async def test_standard_analyze_completes_with_findings(
    advisor: Ovb, built_itinerary: str, harness: Harness
) -> None:
    """Run standard Analyze on the seed → it reaches `completed` and yields a result.

    The feasibility backbone (B5): structural checks + tstzrange overlap + haversine
    drive-time. We assert the async state machine terminates cleanly and produces a
    structured result; the seed is curated-feasible, so we don't *require* a warn —
    the impossible-drive flux finding is proven in the backend's B5 suite and in
    `test_analyze_flags_an_impossible_drive` below when geometry can be injected.
    """
    detail = await flows.analyze_and_wait(harness, advisor, built_itinerary, depth="standard")
    assert str(detail.status) == "completed", detail.error_detail
    assert detail.result is not None
    # Findings is always a list (possibly maturity/missing-field suggestions).
    assert isinstance(detail.findings, list)


@pytest.mark.skip(
    reason="needs API support for setting node starts_at + geo via PATCH to inject an "
    "infeasible jump; the flux-finding itself is covered by the backend B5 suite. Scaffold below."
)
async def test_analyze_flags_an_impossible_drive(
    advisor: Ovb, built_itinerary: str, harness: Harness
) -> None:
    """The B5 acceptance over the wire: an impossible drive-time gap → a `warn` flux finding.

    Intended flow once timed/geo node edits are exposed on the authoring seam (B7):

        1. graph = await advisor.get_graph(built_itinerary)
        2. pick two consecutive timed+located nodes A→B
        3. PATCH B.starts_at so the A→B gap is far shorter than haversine/speed allows
        4. detail = await flows.analyze_and_wait(harness, advisor, built_itinerary)
        5. assert analysis_has_finding(detail, category="location_flux", severity="warn")
    """
    ...


async def test_fill_proposes_feasible_options_for_a_gap(
    advisor: Ovb, built_itinerary: str, harness: Harness
) -> None:
    """AI Fill returns ranked, physically-feasible options for an open window (B6).

    Self-skips when the built graph has no derivable gap or no provider can fill
    it (dark lanes) — never asserts feasibility it can't ground.
    """
    graph = await advisor.get_graph(built_itinerary)
    gap = flows.find_fill_gap(graph)
    if gap is None:
        pytest.skip("no open window between timed nodes to fill")

    # Ground the fill on a completed analysis (the service prefers the latest).
    await flows.analyze_and_wait(harness, advisor, built_itinerary, depth="standard")

    resp = await advisor.fill(built_itinerary, gap_start=gap.start, gap_end=gap.end, min_score=0.0)
    if not resp.proposals:
        pytest.skip("no fill proposals (providers dark for this gap)")

    for p in resp.proposals:
        # Each proposal is addressable (accept = POST /nodes/from-inventory).
        assert p.inventory_source and p.inventory_id
        # Honesty: either it fits the gap, or it is explicitly marked unknown — never
        # asserted-feasible without geometry.
        assert p.fits_in_gap or p.feasibility_unknown
        assert 0.0 <= p.score <= 1.0


async def test_advisor_approves_built_itinerary(advisor: Ovb, built_itinerary: str) -> None:
    """Advisor approves the assembled itinerary → status flips to `approved`.

    The approval gate that makes an itinerary client-visible (the client-sees-it
    half is asserted in the full-loop test, gated on a linked traveler).
    """
    # Approval may require holding the editor lock first (M001 lock/queue) — acquire
    # it defensively; a stack that doesn't require it ignores the extra call.
    with contextlib.suppress(Exception):  # lock is best-effort; approve is the assertion.
        await advisor.lock(built_itinerary)

    itin = await advisor.approve(built_itinerary)
    assert str(itin.status) == "approved", itin.status

    # And the graph read reflects the approved status (linearization-driven surface).
    graph = await advisor.get_graph(built_itinerary)
    assert str(graph.itinerary.status) == "approved"


# ─────────────────────────────────────────────────────────────────────────────
# Advisor private concierge (B7) — the audience axis added in 0018.
#
# The advisor's build aside carries a PRIVATE advisor↔AI workspace (audience
# 'advisor') distinct from the SHARED client thread (audience 'traveler'). The
# two are isolated: reuse is keyed per (client_id, audience), so a client has at
# most one live session of each kind and they never cross-contaminate. These
# assert the session-identity invariants only — no live agent turn — so they are
# green against the mock agent and real Bedrock alike.
# ─────────────────────────────────────────────────────────────────────────────


async def test_advisor_private_concierge_isolated_from_client_thread(
    advisor: Ovb, client_under_test: tuple[str, str]
) -> None:
    """Advisor opens both audiences for one client → two distinct, per-audience-stable sessions.

    Invariants (0018):
      * each session reports the audience it was opened for;
      * the private advisor workspace and the shared client thread are *different*
        sessions (isolation — the traveler never sees the advisor one);
      * reuse is idempotent per (client_id, audience): re-opening the same
        audience returns the same session, opening the other does not.
    """
    client_id, _ = client_under_test

    traveler_thread = await Conversation.open(advisor, client_id=client_id, audience="traveler")
    advisor_workspace = await Conversation.open(advisor, client_id=client_id, audience="advisor")

    # Each session carries the audience it was opened for.
    assert traveler_thread.audience == "traveler"
    assert advisor_workspace.audience == "advisor"

    # Isolation: the private workspace is a different session from the shared thread.
    assert advisor_workspace.session_id != traveler_thread.session_id

    # Reuse is keyed per (client_id, audience): same audience → same session.
    reopened_advisor = await Conversation.open(advisor, client_id=client_id, audience="advisor")
    assert reopened_advisor.session_id == advisor_workspace.session_id

    reopened_traveler = await Conversation.open(advisor, client_id=client_id, audience="traveler")
    assert reopened_traveler.session_id == traveler_thread.session_id


async def test_traveler_cannot_open_advisor_audience(
    traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """A traveler asking for the private advisor workspace is refused with existence-hiding.

    Defense-in-depth from `open_or_reuse_session`: a traveler actor is gated to
    the 'traveler' audience; requesting 'advisor' resolves to FORBIDDEN surfaced
    as 404 (we don't even confirm the advisor session could exist). Self-skips
    when no linked-traveler identity is provisioned on this machine.
    """
    # The traveler's own (shared) thread opens fine — the control case.
    own_thread = await Conversation.open(
        traveler, client_id=linked_traveler_client_id, audience="traveler"
    )
    assert own_thread.audience == "traveler"

    # But the private advisor workspace is hidden: 404, not 403.
    with pytest.raises(ApiError) as exc_info:
        await Conversation.open(
            traveler, client_id=linked_traveler_client_id, audience="advisor"
        )
    assert exc_info.value.status == 404, exc_info.value
