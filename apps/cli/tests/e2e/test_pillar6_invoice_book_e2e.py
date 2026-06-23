"""Pillar 6 — One or more invoices total all booked inventory (pay-before-book).

Demo-script stage 6 (mvp.md §7): *"Advisor issues a deposit invoice + balance
invoice totalling the booked inventory; traveler pays via Braintree sandbox; paid
nodes flip to booked; advisor records supplier confirmations → confirmed. The
reconciliation check passes: booked inventory ⇔ paid invoice lines."*

Acceptance (mvp.md Pillar 6):
  - Bookable nodes carry first-class numeric cost + currency. ✅ (B4 — asserted in
    Pillar 3's `test_cost_rolls_up_per_currency`; the cost spine is real today.)
  - Advisor groups approved bookable nodes into one or more invoices; each total =
    Σ its line items; line items reference the nodes they pay for.
  - Traveler can view + pay invoices (Braintree, D-PAY).
  - Money gate: a node moves approved → booked only when covered by a paid (or
    issued, per override) invoice line. Σ(paid lines) ⇔ Σ(booked node costs).

Status: 🔨 NOT BUILT except node cost (B4). No invoices, line items, payment, or
money gate. These scaffolds `skip_until` M005; the reconciliation test is wired to
`ovb.invariants.money_gate_reconciles` (an honest `NotImplementedError` stub today)
so it becomes a real assertion the moment I3 lands.
"""

from __future__ import annotations

import flows
import pytest

pytestmark = pytest.mark.e2e


async def test_advisor_assembles_invoices_over_booked_nodes() -> None:
    """I1 — N invoices over one itinerary; each total = Σ its lines, referencing nodes.

    Intended flow (M005/I1):

        # 1. Group approved bookable nodes into a deposit + a balance invoice.
        deposit = await advisor.create_invoice(itin, label="Deposit", node_ids=[a, b])
        balance = await advisor.create_invoice(itin, label="Balance", node_ids=[c, d])

        # 2. Each invoice's total equals the sum of its line items.
        for inv in (deposit, balance):
            assert inv.total == sum(li.amount for li in inv.line_items)
            assert {li.node_id for li in inv.line_items} <= set(approved_node_ids)

        # 3. Collectively the invoices total exactly the booked inventory (per currency),
        #    reconciled against `cost_totals(graph, statuses={"approved","booked"})`.
    """
    flows.skip_until("M005/I1", "invoices + line items (group approved bookable nodes)")


async def test_traveler_pays_invoice_via_braintree_sandbox() -> None:
    """I2 — traveler pays an issued invoice in the Braintree sandbox (D-PAY).

    Intended flow (M005/I2 — references voyage-site brainTreeGateway.ts):

        await advisor.issue_invoice(deposit.id)             # draft → issued
        token = await traveler.braintree_client_token(deposit.id)
        nonce = braintree_sandbox_pay(token, test_card)     # drop-in / sandbox nonce
        await traveler.pay_invoice(deposit.id, nonce=nonce)

        paid = await traveler.get_invoice(deposit.id)
        assert str(paid.status) == "paid"
        assert paid.payments and paid.payments[0].amount == paid.total
        # Invoice + payment history visible to the traveler.
    """
    flows.skip_until("M005/I2", "Braintree payment (client token + pay + webhook → paid)")


async def test_money_gate_blocks_unpaid_booking_and_reconciles() -> None:
    """I3 — pay-before-book money gate + the reconciliation invariant.

    `ovb.invariants.money_gate_reconciles` raises `NotImplementedError` today; it
    becomes the assertion here when I3 lands. Intended flow (M005/I3):

        # 1. An unpaid approved node cannot be booked.
        with pytest.raises(ApiError) as exc:
            await advisor.book_node(itin, node_id)          # no covering paid line
        assert exc.value.status == 409

        # 2. After payment, the node books; advisor records a supplier confirmation #.
        await advisor.book_node(itin, node_id)              # now covered by a paid line
        await advisor.record_confirmation(itin, node_id, supplier_ref="ABC123")  # → confirmed

        # 3. The reconciliation invariant holds: Σ(paid invoice lines for nodes) ⇔
        #    Σ(booked node costs), re-priced amount, no double-billing.
        assert_no_violations(money_gate_reconciles(invoices, graph))

        # 4. (D-PAY) advisor override may book on an *issued* line — logged + asserted.
    """
    flows.skip_until("M005/I3", "money gate + booking workflow + reconciliation invariant")
