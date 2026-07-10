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
NODE_STATUSES = {"pending", "approved", "booked", "confirmed", "discarded"}
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


# ── M004 gate / fork invariants ──────────────────────────────────────────────

# Mirrors services/itineraries._FIRMED_STATUSES — the lifecycle states a node is
# committed to and the G1 gate makes immutable (wherever the node lives).
FIRMED_STATUSES = {"approved", "booked", "confirmed"}


def status_actor_gate_holds(graph: gm.GraphResponse) -> list[Violation]:
    """M004/G1 — the booked/confirmed immutability contract, read off the graph.

    The dynamic half (a traveler/agent edit returns 409) is asserted directly in
    the e2e with ``pytest.raises``; this is the *static* half: every firmed node
    must advertise ``lock_reason='status_locked'`` so the agent can explain a
    refusal, and no pre-firmed node may carry a stale lock_reason. Together they
    are the observable surface of ``services/itineraries._check_status_gate``.
    """
    out: list[Violation] = []
    for node in graph.nodes:
        status = str(node.status)
        lock_reason = getattr(node, "lock_reason", None)
        if status in FIRMED_STATUSES and lock_reason != "status_locked":
            out.append(
                Violation(
                    "missing_lock_reason",
                    f"firmed node {node.id} ({status}) lacks lock_reason=status_locked",
                )
            )
        if status not in FIRMED_STATUSES and lock_reason:
            out.append(
                Violation(
                    "spurious_lock_reason",
                    f"pre-firmed node {node.id} ({status}) carries lock_reason {lock_reason!r}",
                )
            )
    return out


def fork_lineage_holds(fork: gm.GraphResponse, baseline: gm.GraphResponse) -> list[Violation]:
    """M004/G2 — a fork is a faithful versioned clone of its baseline.

    Every fork node carries ``forked_from_node_id`` lineage to a distinct baseline
    node; booked/confirmed nodes carry over with status preserved (carried locked);
    the fork is a different itinerary whose ``forked_from_id`` is the baseline.
    """
    out: list[Violation] = []
    baseline_ids = {str(n.id) for n in baseline.nodes}
    baseline_status = {str(n.id): str(n.status) for n in baseline.nodes}

    fork_itin = fork.itinerary
    if getattr(fork_itin, "forked_from_id", None) is None:
        out.append(Violation("fork_no_lineage", f"fork {fork_itin.id} has no forked_from_id"))
    if str(fork_itin.id) == str(baseline.itinerary.id):
        out.append(Violation("fork_not_distinct", "fork shares the baseline's id"))

    seen_origins: set[str] = set()
    for node in fork.nodes:
        origin = getattr(node, "forked_from_node_id", None)
        if origin is None:
            out.append(Violation("node_no_lineage", f"fork node {node.id} has no lineage"))
            continue
        origin = str(origin)
        if origin not in baseline_ids:
            out.append(Violation("lineage_dangling", f"fork node {node.id} → unknown {origin}"))
        if origin in seen_origins:
            out.append(Violation("lineage_duplicate", f"two fork nodes share origin {origin}"))
        seen_origins.add(origin)
        # Carried-locked: a baseline booked/confirmed node keeps its status in the fork.
        if baseline_status.get(origin) in {"booked", "confirmed"} and (
            str(node.status) != baseline_status[origin]
        ):
            out.append(
                Violation(
                    "fork_unlocked_booking",
                    f"fork node {node.id} demoted a carried {baseline_status[origin]} node",
                )
            )
    return out


def reconcile_holds(
    live: gm.GraphResponse,
    accepted: list[Any],
    baseline: gm.GraphResponse,
) -> list[Violation]:
    """M004/G3 — after reconcile, accepted changes are folded into the live
    baseline and no booked/confirmed node was mutated.

    ``accepted`` is the list of accepted diff changes (``NodeChangeResponse``);
    ``baseline`` is the pre-reconcile baseline graph, ``live`` the post-reconcile
    one. Each accepted ``removed`` is absent from ``live``; each accepted
    ``changed`` onto a pre-firmed node reflects the fork's value. A change onto a
    booked/confirmed node is *expected* to be kept (immutability) — verified
    unchanged instead of folded in.
    """
    out: list[Violation] = []
    before_by_id = {str(n.id): n for n in baseline.nodes}
    live_by_id = {str(n.id): n for n in live.nodes}
    firmed = {"booked", "confirmed"}

    # Booked/confirmed baseline nodes are never changed by reconcile.
    for nid, node in before_by_id.items():
        if str(node.status) in firmed:
            live_node = live_by_id.get(nid)
            if live_node is None:
                out.append(Violation("reconcile_dropped_booking", f"booked node {nid} removed"))
            elif str(live_node.title) != str(node.title) or str(live_node.status) != str(
                node.status
            ):
                out.append(Violation("reconcile_changed_booking", f"booked node {nid} mutated"))

    for change in accepted:
        kind = str(getattr(change, "kind", ""))
        raw_bnid = getattr(change, "baseline_node_id", None)
        bnid = str(raw_bnid) if raw_bnid is not None else None
        if bnid is None:
            continue
        before_node = before_by_id.get(bnid)
        was_firmed = before_node is not None and str(before_node.status) in firmed
        if kind == "removed":
            if bnid in live_by_id and not was_firmed:
                out.append(
                    Violation("reconcile_kept_removed", f"node {bnid} still present after remove")
                )
        elif kind == "changed" and bnid in live_by_id and not was_firmed:
            after = getattr(change, "after", None) or {}
            fields = list(getattr(change, "fields", None) or [])
            if (
                "title" in fields
                and "title" in after
                and str(live_by_id[bnid].title) != str(after["title"])
            ):
                out.append(
                    Violation("reconcile_unapplied_change", f"node {bnid} title not folded in")
                )
    return out


def money_gate_reconciles(report: gm.ReconciliationResponse) -> list[Violation]:
    """M005/I3 — Σ(paid invoice lines) ⇔ Σ(booked node costs), per currency.

    Reads the backend's authoritative reconciliation report (``GET
    /itinerary/{id}/reconciliation``) so the CLI/e2e assertion can't drift from
    the server's own computation over the 0023 ledger + the 0025 bookings. Every
    per-node violation (booked-but-unpaid, under/over-charge from a re-price) and
    every unbalanced currency row becomes a :class:`Violation`; a balanced report
    yields ``[]``.
    """
    out: list[Violation] = []
    for v in report.violations or []:
        out.append(
            Violation(
                f"money_gate_{v.code}",
                f"node {v.node_id}: booked {v.currency} {v.booked_amount} vs paid {v.paid_amount}",
            )
        )
    for row in report.rows or []:
        if not row.balanced:
            out.append(
                Violation(
                    "money_gate_imbalance",
                    f"{row.currency}: Σ booked {row.booked_total} ≠ Σ paid {row.paid_total}",
                )
            )
    # Defensive: the server's own `balanced` flag must agree with what we surfaced.
    if not report.balanced and not out:
        out.append(Violation("money_gate_unbalanced", "reconciliation reports unbalanced"))
    return out
