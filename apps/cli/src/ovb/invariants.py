"""Reusable invariant checks — written once, used by both the CLI and the e2e tests.

Each check returns a list of :class:`Violation` (so the CLI can render them and
keep going); :func:`assert_no_violations` turns them into a pytest failure.
Checks that depend on milestones not yet built (the M004 status×actor gate, the
M005 money-gate reconciliation) are present as honest stubs that raise rather
than silently passing — so they show up as TODO coverage, not false green.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ovb._compat import unwrap_root
from ovb._generated import models as gm

# Mirrors the NodeStatus / NodeType / EdgeType enums in the schema spine.
NODE_STATUSES = {"idea", "proposed", "approved", "booked", "confirmed", "discarded"}
BOOKABLE_TYPES = {"flight", "hotel", "experience", "meal"}


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    message: str
    severity: str = "error"  # error | warn

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


def assert_no_violations(violations: list[Violation]) -> None:
    """Raise if any error-severity violation is present (e2e gate)."""
    errors = [v for v in violations if v.severity == "error"]
    if errors:
        joined = "\n  ".join(str(v) for v in errors)
        raise AssertionError(f"{len(errors)} invariant violation(s):\n  {joined}")


def graph_integrity(graph: gm.GraphResponse) -> list[Violation]:
    """Structural invariants the graph must always satisfy."""
    out: list[Violation] = []
    node_ids = {str(n.id) for n in graph.nodes}

    for node in graph.nodes:
        status = str(node.status)
        if status not in NODE_STATUSES:
            out.append(Violation("bad_status", f"node {node.id} has status {status!r}"))
        # Cost is both-or-neither (mirrors the DB CHECK nodes_cost_amount_currency_together).
        has_amt = node.cost_amount is not None
        has_cur = node.cost_currency is not None
        if has_amt != has_cur:
            out.append(
                Violation("cost_half_set", f"node {node.id} has cost_amount xor cost_currency")
            )

    for edge in graph.edges:
        if str(edge.from_node_id) not in node_ids:
            out.append(Violation("dangling_edge", f"edge {edge.id} from-node not in graph"))
        if str(edge.to_node_id) not in node_ids:
            out.append(Violation("dangling_edge", f"edge {edge.id} to-node not in graph"))

    return out


def _to_decimal(value: Any) -> Decimal | None:
    value = unwrap_root(value)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def cost_totals(graph: gm.GraphResponse, *, statuses: set[str] | None = None) -> dict[str, Decimal]:
    """Sum node costs grouped by currency (non-discarded nodes).

    Per-person amounts are summed at face value — party-size expansion is M005.
    Mirrors ``services/node_cost.sum_node_costs`` so a CLI total reconciles with
    the backend's.
    """
    totals: dict[str, Decimal] = {}
    for node in graph.nodes:
        if str(node.status) == "discarded":
            continue
        if statuses is not None and str(node.status) not in statuses:
            continue
        amount = _to_decimal(node.cost_amount)
        currency = node.cost_currency
        if amount is None or not currency:
            continue
        totals[currency] = totals.get(currency, Decimal(0)) + amount
    return totals


def redaction_leak(text: str, sentinels: list[str]) -> list[Violation]:
    """Flag any sentinel (Dossier/OSINT/net-worth content) appearing in ``text``.

    The agent must never surface Dossier or OSINT verbatim; feed those fact
    texts as sentinels to assert a turn's prose (or a log blob) stays clean.
    """
    haystack = text.lower()
    out: list[Violation] = []
    for sentinel in sentinels:
        needle = sentinel.strip().lower()
        if needle and needle in haystack:
            out.append(Violation("redaction_leak", f"disclosed sentinel {sentinel!r}"))
    return out


def analysis_has_finding(
    analysis: gm.AnalysisDetailResponse,
    *,
    category: str | None = None,
    severity: str | None = None,
) -> bool:
    """True if the analysis emitted a finding matching category/severity."""
    for finding in analysis.findings:
        if category is not None and finding.category != category:
            continue
        if severity is not None and str(finding.severity) != severity:
            continue
        return True
    return False


def require_finding(
    analysis: gm.AnalysisDetailResponse,
    *,
    category: str | None = None,
    severity: str | None = None,
) -> None:
    if not analysis_has_finding(analysis, category=category, severity=severity):
        raise AssertionError(
            f"expected a finding (category={category}, severity={severity}) "
            f"in analysis {analysis.id}; got {[f.category for f in analysis.findings]}"
        )


# ── milestone-gated invariants (honest stubs) ────────────────────────────────
def status_actor_gate_holds(*_args: Any, **_kwargs: Any) -> list[Violation]:
    """M004/G1 — booked/confirmed immutability across actor × status."""
    raise NotImplementedError(
        "status×actor gate lands in M004/G1 (services/itineraries._check_status_gate)"
    )


def money_gate_reconciles(*_args: Any, **_kwargs: Any) -> list[Violation]:
    """M005/I3 — Σ(paid invoice lines) ⇔ Σ(booked node costs), re-priced amount."""
    raise NotImplementedError(
        "money-gate reconciliation lands in M005/I3 (needs invoices + bookings)"
    )
