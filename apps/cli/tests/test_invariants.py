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
    reconcile_holds,
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
            status="pending",
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


def test_money_gate_reconciles_reads_the_backend_report() -> None:
    """M005/I3 landed: a balanced report yields no violations; an imbalance + a
    per-node discrepancy each surface as a Violation."""
    from ovb.invariants import assert_no_violations

    balanced = gm.ReconciliationResponse(
        balanced=True,
        rows=[
            gm.ReconciliationRowResponse(
                currency="USD", paid_total="1000.00", booked_total="1000.00", balanced=True
            )
        ],
        violations=[],
    )
    assert money_gate_reconciles(balanced) == []

    unbalanced = gm.ReconciliationResponse(
        balanced=False,
        rows=[
            gm.ReconciliationRowResponse(
                currency="USD", paid_total="0.00", booked_total="500.00", balanced=False
            )
        ],
        violations=[
            gm.ReconciliationViolationResponse(
                node_id="22222222-2222-2222-2222-222222222222",
                code="booked_unpaid",
                currency="USD",
                booked_amount="500.00",
                paid_amount="0.00",
            )
        ],
    )
    out = money_gate_reconciles(unbalanced)
    codes = {v.code for v in out}
    assert "money_gate_booked_unpaid" in codes
    assert "money_gate_imbalance" in codes
    with pytest.raises(AssertionError):
        assert_no_violations(out)


def test_status_actor_gate_holds_checks_lock_reason() -> None:
    """G1 landed: a firmed node must advertise lock_reason; a pre-firmed must not."""
    iid = "11111111-1111-1111-1111-111111111111"
    booked_id = "22222222-2222-2222-2222-222222222222"
    pending_id = "33333333-3333-3333-3333-333333333333"
    clean = make_graph(
        iid,
        nodes=[
            make_node(booked_id, iid, status="booked", lock_reason="status_locked"),
            make_node(pending_id, iid, status="pending", lock_reason=None),
        ],
    )
    assert status_actor_gate_holds(clean) == []

    # A booked node missing its lock_reason is a contract violation.
    broken = make_graph(iid, nodes=[make_node(booked_id, iid, status="booked", lock_reason=None)])
    violations = status_actor_gate_holds(broken)
    assert any(v.code == "missing_lock_reason" for v in violations)


def _change(**over: object) -> gm.NodeChangeResponse:
    base: dict[str, object] = {"change_id": ITIN, "kind": "changed", "fields": []}
    base.update(over)
    return gm.NodeChangeResponse.model_validate(base)


def test_reconcile_holds_folds_accepted_and_keeps_booking() -> None:
    """G3: accepted changes land in the live baseline; the booking is untouched."""
    iid = ITIN
    keep = "22222222-2222-2222-2222-222222222222"
    booked = "33333333-3333-3333-3333-333333333333"
    drop = "44444444-4444-4444-4444-444444444444"

    baseline = make_graph(
        iid,
        nodes=[
            make_node(keep, iid, status="pending", title="old"),
            make_node(booked, iid, status="booked", title="Aman", lock_reason="status_locked"),
            make_node(drop, iid, status="pending", title="to remove"),
        ],
    )
    # Accepted: keep's title folded in, drop removed; the booking carries over intact.
    live = make_graph(
        iid,
        nodes=[
            make_node(keep, iid, status="pending", title="new"),
            make_node(booked, iid, status="booked", title="Aman", lock_reason="status_locked"),
        ],
    )
    accepted = [
        _change(
            change_id=keep,
            kind="changed",
            baseline_node_id=keep,
            fields=["title"],
            after={"title": "new"},
        ),
        _change(change_id=drop, kind="removed", baseline_node_id=drop, fields=[]),
    ]
    assert reconcile_holds(live, accepted, baseline) == []


def test_reconcile_holds_flags_unapplied_change_and_mutated_booking() -> None:
    """G3: a change that didn't fold in, and a mutated booking, are violations."""
    iid = ITIN
    keep = "22222222-2222-2222-2222-222222222222"
    booked = "33333333-3333-3333-3333-333333333333"

    baseline = make_graph(
        iid,
        nodes=[
            make_node(keep, iid, status="pending", title="old"),
            make_node(booked, iid, status="booked", title="Aman", lock_reason="status_locked"),
        ],
    )
    # The accepted title was NOT applied, and the booking's title was mutated.
    live = make_graph(
        iid,
        nodes=[
            make_node(keep, iid, status="pending", title="old"),
            make_node(booked, iid, status="booked", title="Tampered", lock_reason="status_locked"),
        ],
    )
    accepted = [
        _change(
            change_id=keep,
            kind="changed",
            baseline_node_id=keep,
            fields=["title"],
            after={"title": "new"},
        ),
    ]
    codes = {v.code for v in reconcile_holds(live, accepted, baseline)}
    assert "reconcile_unapplied_change" in codes
    assert "reconcile_changed_booking" in codes
