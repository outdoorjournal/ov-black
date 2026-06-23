"""Reusable invariant checks (offline)."""

from decimal import Decimal

import pytest

from _helpers import make_graph, make_node
from ovb._generated import models as gm
from ovb.invariants import (
    analysis_has_finding,
    assert_no_violations,
    cost_totals,
    graph_integrity,
    money_gate_reconciles,
    redaction_leak,
    require_finding,
    status_actor_gate_holds,
)

ITIN = "11111111-1111-1111-1111-111111111111"


def test_graph_integrity_clean() -> None:
    g = make_graph(ITIN, nodes=[make_node("a" * 8 + "-0000-0000-0000-000000000001", ITIN)])
    assert graph_integrity(g) == []


def test_graph_integrity_flags_dangling_edge() -> None:
    n1 = "22222222-2222-2222-2222-222222222222"
    g = make_graph(
        ITIN,
        nodes=[make_node(n1, ITIN)],
        edges=[
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "itinerary_id": ITIN,
                "from_node_id": n1,
                "to_node_id": "44444444-4444-4444-4444-444444444444",  # missing
                "type": "follows",
                "metadata": {},
            }
        ],
    )
    violations = graph_integrity(g)
    assert any(v.code == "dangling_edge" for v in violations)
    with pytest.raises(AssertionError):
        assert_no_violations(violations)


def test_graph_integrity_flags_half_set_cost() -> None:
    n = make_node(
        "55555555-5555-5555-5555-555555555555", ITIN, cost_amount="100.00", cost_currency=None
    )
    violations = graph_integrity(make_graph(ITIN, nodes=[n]))
    assert any(v.code == "cost_half_set" for v in violations)


def test_cost_totals_groups_by_currency_and_unwraps_rootmodel() -> None:
    nodes = [
        make_node(
            "00000000-0000-0000-0000-000000000001", ITIN, cost_amount="1200.00", cost_currency="USD"
        ),
        make_node(
            "00000000-0000-0000-0000-000000000002", ITIN, cost_amount="300.00", cost_currency="USD"
        ),
        make_node(
            "00000000-0000-0000-0000-000000000003", ITIN, cost_amount="500.00", cost_currency="EUR"
        ),
        make_node(
            "00000000-0000-0000-0000-000000000004",
            ITIN,
            status="discarded",
            cost_amount="999.00",
            cost_currency="USD",
        ),
    ]
    totals = cost_totals(make_graph(ITIN, nodes=nodes))
    assert totals == {"USD": Decimal("1500.00"), "EUR": Decimal("500.00")}


def test_cost_totals_status_filter() -> None:
    nodes = [
        make_node(
            "00000000-0000-0000-0000-000000000005",
            ITIN,
            status="approved",
            cost_amount="10.00",
            cost_currency="USD",
        ),
        make_node(
            "00000000-0000-0000-0000-000000000006",
            ITIN,
            status="proposed",
            cost_amount="20.00",
            cost_currency="USD",
        ),
    ]
    totals = cost_totals(make_graph(ITIN, nodes=nodes), statuses={"approved"})
    assert totals == {"USD": Decimal("10.00")}


def test_redaction_leak_detects_sentinels() -> None:
    out = redaction_leak("As you mentioned, your NET WORTH is high", ["net worth", "linkedin"])
    assert len(out) == 1 and out[0].code == "redaction_leak"
    assert redaction_leak("a clean reply", ["net worth"]) == []


def _analysis(findings: list[dict]) -> gm.AnalysisDetailResponse:
    return gm.AnalysisDetailResponse.model_validate(
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "itinerary_id": ITIN,
            "status": "completed",
            "depth": "standard",
            "summary": "ok",
            "error_detail": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-06-21T00:00:00Z",
            "scope": {},
            "result": {},
            "external_calls": [],
            "findings": findings,
        }
    )


def test_analysis_finding_helpers() -> None:
    analysis = _analysis(
        [
            {
                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "node_id": None,
                "severity": "warn",
                "category": "location_flux",
                "message": "drive too tight",
                "evidence": {"km": 400},
                "suggested_fix": None,
            }
        ]
    )
    assert analysis_has_finding(analysis, category="location_flux", severity="warn")
    assert not analysis_has_finding(analysis, category="weather")
    require_finding(analysis, category="location_flux")
    with pytest.raises(AssertionError):
        require_finding(analysis, category="weather")


def test_milestone_gated_checks_are_honest_stubs() -> None:
    with pytest.raises(NotImplementedError):
        status_actor_gate_holds()
    with pytest.raises(NotImplementedError):
        money_gate_reconciles()
