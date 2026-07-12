"""Graph digest rendering (AGT-2) — the per-turn "Live plan state" block.

Pure tests over :func:`app.services.graph_digest.render_graph_digest`; the
async loader is thin SELECT plumbing exercised by the live stack. What matters
here: every derived display-status bucket renders with its publish-flow hint
(and the fork framing wins when pinned to a working copy), counts / totals /
uninvoiced / reconcile / analysis lines appear exactly when they have
something to say, and an empty plan degrades gracefully.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.models import InvoiceStatus, NodeStatus
from app.services.billing_summary import (
    BillingCurrencyRow,
    BillingState,
    InvoiceBrief,
    UnbilledNode,
)
from app.services.display_status import DisplayStatus
from app.services.graph_digest import (
    _viewing_when,
    render_graph_digest,
    render_viewing_context,
)


def _digest(**overrides: object) -> str:
    base: dict = {
        "display_status": DisplayStatus.in_studio,
        "is_fork": False,
        "status_counts": {},
        "totals": {},
        "party_size": 1,
        "billing": None,
        "reconcile_requested": False,
        "analysis_block_count": None,
        "analysis_warn_count": None,
    }
    base.update(overrides)
    return render_graph_digest(**base)


def test_empty_plan_renders_status_and_no_cards() -> None:
    out = _digest()
    assert out.startswith("Live plan state")
    assert "Status: in the studio" in out
    assert "Cards: none yet" in out
    assert "Trip total" not in out
    assert "Uninvoiced" not in out


def test_every_display_status_carries_its_publish_flow_hint() -> None:
    in_studio = _digest(display_status=DisplayStatus.in_studio)
    with_traveler = _digest(display_status=DisplayStatus.with_traveler)
    approved = _digest(display_status=DisplayStatus.approved)
    assert "in the studio" in in_studio
    assert "with the traveler" in with_traveler
    assert "the traveler has approved" in approved


def test_fork_hint_wins_over_display_status() -> None:
    out = _digest(display_status=DisplayStatus.with_traveler, is_fork=True)
    assert "working version" in out
    assert "with the traveler —" not in out


def test_card_counts_render_in_lifecycle_order_with_lock_note() -> None:
    out = _digest(
        status_counts={
            NodeStatus.pending: 8,
            NodeStatus.approved: 3,
            NodeStatus.booked: 1,
        }
    )
    assert "Cards: 12 — 8 pending, 3 approved, 1 booked" in out
    assert "booked/confirmed cards are locked" in out


def test_discarded_cards_never_render() -> None:
    out = _digest(status_counts={NodeStatus.pending: 2, NodeStatus.discarded: 5})
    assert "Cards: 2 — 2 pending" in out
    assert "discarded" not in out


def test_totals_render_per_currency_with_party() -> None:
    out = _digest(
        totals={"USD": Decimal("24300.00"), "JPY": Decimal("150000")},
        party_size=4,
    )
    assert "Trip total: 150000 JPY + 24300.00 USD (party of 4)" in out


def test_billing_lines_render_only_when_nonzero() -> None:
    billing = BillingState(
        rows=[
            BillingCurrencyRow(
                currency="USD",
                trip_total=Decimal("24300.00"),
                invoiced=Decimal("15200.00"),
                paid=Decimal("12000.00"),
                outstanding=Decimal("3200.00"),
                uninvoiced=Decimal("9100.00"),
                uninvoiced_count=5,
            )
        ],
        unbilled_nodes=[
            UnbilledNode(
                node_id=uuid.uuid4(),
                title="Ryokan",
                currency="USD",
                effective=Decimal("1200.00"),
                charged=Decimal("200.00"),
                remaining=Decimal("1000.00"),
            )
        ],
        invoices=[
            InvoiceBrief(
                invoice_id=uuid.uuid4(),
                label="Deposit",
                status=InvoiceStatus.issued,
                currency="USD",
                total=Decimal("15200.00"),
                paid=Decimal("12000.00"),
            )
        ],
    )
    out = _digest(billing=billing)
    assert "Invoiced: 15200.00 USD (12000.00 paid, 3200.00 outstanding)" in out
    assert "Uninvoiced: 9100.00 USD across 5 approved cards" in out

    silent = _digest(
        billing=BillingState(
            rows=[
                BillingCurrencyRow(
                    currency="USD",
                    trip_total=Decimal("0.00"),
                    invoiced=Decimal("0.00"),
                    paid=Decimal("0.00"),
                    outstanding=Decimal("0.00"),
                    uninvoiced=Decimal("0.00"),
                    uninvoiced_count=0,
                )
            ],
            unbilled_nodes=[],
            invoices=[],
        )
    )
    assert "Invoiced" not in silent
    assert "Uninvoiced" not in silent


def test_reconcile_and_analysis_lines() -> None:
    out = _digest(
        reconcile_requested=True,
        analysis_block_count=1,
        analysis_warn_count=2,
    )
    assert "asked staff to merge this alternative" in out
    assert "Latest analysis: 1 blocking, 2 warning findings" in out

    clean = _digest(analysis_block_count=0, analysis_warn_count=0)
    assert "Latest analysis" not in clean
    assert "merge this alternative" not in clean


# ── On-screen focus cue (ambient "viewing" context) ──────────────────────────


def test_viewing_context_full_card() -> None:
    out = render_viewing_context(
        title="Aman Kyoto",
        node_type="hotel",
        status="pending",
        when="2026-09-14 15:00",
        cost="1200.00 USD",
    )
    assert "Aman Kyoto" in out
    assert "hotel" in out and "pending" in out
    assert "2026-09-14 15:00" in out and "1200.00 USD" in out
    # The ambient discipline: resolve deixis, but never announce the screen-peek.
    assert "this" in out and "it" in out
    assert "don't\nannounce" in out or "don't announce" in out


def test_viewing_context_bare_card_omits_when_and_cost() -> None:
    out = render_viewing_context(
        title="A mystery experience",
        node_type="experience",
        status="approved",
        when=None,
        cost=None,
    )
    assert "(experience, approved)" in out
    # No trailing comma / empty slot when when+cost are absent.
    assert ", ," not in out


def test_viewing_context_untitled_card_degrades() -> None:
    out = render_viewing_context(
        title="   ",
        node_type="note",
        status="pending",
        when=None,
        cost=None,
    )
    assert "an untitled card" in out


class _FakeRange:
    def __init__(self, lower: object) -> None:
        self.lower = lower


class _FakeDatetime:
    def strftime(self, fmt: str) -> str:
        return "2026-09-14 15:00"


def test_viewing_when_reads_range_lower() -> None:
    assert _viewing_when(_FakeRange(_FakeDatetime())) == "2026-09-14 15:00"


def test_viewing_when_none_for_missing_or_open_lower() -> None:
    assert _viewing_when(None) is None
    assert _viewing_when(_FakeRange(None)) is None
