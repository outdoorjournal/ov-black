"""Pillar 6 — Invoicing → pay → money gate → book → confirm → reconcile (M005).

Demo-script stage 6 (mvp.md §7): *"Advisor issues invoice(s) totalling the
booked inventory; traveler pays via Braintree sandbox; paid nodes flip to booked;
advisor records supplier confirmations → confirmed. The reconciliation check
passes: booked inventory ⇔ paid invoice lines."*

The three slices of M005 over a live stack, via the same ``ovb`` SDK the UI uses:

  - I1 — an invoice assembled over an approved bookable node; total = Σ its lines,
    each line references the node it pays for.
  - I2 — the issued invoice is paid with a tokenized nonce (Fake gateway / Braintree
    sandbox); it flips to ``paid`` with a ``succeeded`` payment.
  - I3 — the money gate: an unpaid approved node can't be booked (409); once a
    covering paid line exists it books, a supplier confirmation # advances it to
    ``confirmed``, and the reconciliation invariant (Σ paid lines ⇔ Σ booked node
    costs) holds — asserted via ``ovb.invariants.money_gate_reconciles``.

The pay step uses ``fake-valid-nonce`` (valid for both the Fake gateway and the
Braintree sandbox); where no gateway is wired (``payments_unconfigured``) the
paid-dependent steps self-skip rather than false-fail.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from ovb.errors import ApiError
from ovb.invariants import assert_no_violations, money_gate_reconciles
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e

# I3 books a NON-flight bookable node so the flow doesn't need a live flight offer
# (the flight re-price-before-book path is covered by the backend's test_bookings).
_NON_FLIGHT_BOOKABLE = {"hotel", "experience", "meal"}
_FIRMED = {"approved", "booked", "confirmed"}


def _bookable_node(graph: Any) -> Any | None:
    return next((n for n in graph.nodes if str(n.type) in _NON_FLIGHT_BOOKABLE), None)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


async def _approved_priced_node(advisor: Ovb, itin: str, *, amount: str, currency: str) -> str:
    """Make a non-flight bookable node approved + priced; return its id."""
    node = _bookable_node(await advisor.get_graph(itin))
    if node is None:
        pytest.skip("no non-flight bookable node in the seeded itinerary to book")
    node_id = str(node.id)
    if str(node.status) in _FIRMED:
        await advisor.update_node(itin, node_id, fields={"status": "pending"})
    await advisor.update_node(
        itin,
        node_id,
        fields={"cost_amount": amount, "cost_currency": currency, "cost_kind": "total"},
    )
    await advisor.update_node(itin, node_id, fields={"status": "approved"})
    return node_id


async def _pay_for_node(advisor: Ovb, itin: str, node_id: str, *, currency: str) -> Any:
    """Assemble a one-line invoice charging the node, issue it, pay it. Returns the
    paid invoice; self-skips when no gateway is wired."""
    invoice = await advisor.create_invoice(itin, label="Deposit", currency=currency)
    await advisor.add_invoice_line(str(invoice.id), node_id=node_id)
    await advisor.issue_invoice(str(invoice.id))
    try:
        return await advisor.pay_invoice(str(invoice.id), payment_method_nonce="fake-valid-nonce")
    except ApiError as exc:
        if exc.detail == "payments_unconfigured":
            pytest.skip("no payment gateway wired on this target (prod without keys)")
        raise


async def test_advisor_assembles_invoices_over_booked_nodes(
    advisor: Ovb, built_itinerary: str
) -> None:
    """I1 — an invoice over an approved bookable node: total = Σ lines, lines ref nodes."""
    itin = built_itinerary
    node_id = await _approved_priced_node(advisor, itin, amount="1000.00", currency="USD")

    invoice = await advisor.create_invoice(itin, label="Deposit", currency="USD")
    charge = await advisor.add_invoice_line(str(invoice.id), node_id=node_id)
    assert str(charge.kind) == "charge"
    assert _dec(charge.amount) == Decimal("1000.00")

    got = await advisor.get_invoice(str(invoice.id))
    assert _dec(got.total) == _dec(charge.amount)  # total = Σ its line items
    assert any(str(li.node_id) == node_id for li in got.lines)  # line references the node


async def test_traveler_pays_invoice_via_braintree_sandbox(
    advisor: Ovb, built_itinerary: str
) -> None:
    """I2 — an issued invoice is paid with a tokenized nonce; it flips to paid."""
    itin = built_itinerary
    node_id = await _approved_priced_node(advisor, itin, amount="500.00", currency="USD")
    paid = await _pay_for_node(advisor, itin, node_id, currency="USD")
    assert str(paid.status) == "paid"
    succeeded = [p for p in paid.payments if str(p.status) == "succeeded"]
    assert len(succeeded) == 1
    assert succeeded[0].gateway_reference


async def test_money_gate_blocks_unpaid_booking_and_reconciles(
    advisor: Ovb, built_itinerary: str
) -> None:
    """I3 — pay-before-book money gate + the reconciliation invariant."""
    itin = built_itinerary
    node_id = await _approved_priced_node(advisor, itin, amount="1000.00", currency="USD")

    # 1. An unpaid approved node cannot be booked.
    with pytest.raises(ApiError) as exc:
        await advisor.book_node(itin, node_id)
    assert exc.value.status == 409
    assert exc.value.detail == "node_not_paid"

    # 2. Pay a covering invoice line (self-skips where no gateway is wired).
    await _pay_for_node(advisor, itin, node_id, currency="USD")

    # 3. Now it books, and a supplier confirmation advances it to confirmed.
    booking = await advisor.book_node(itin, node_id)
    assert str(booking.node_status) == "booked"
    assert booking.override_unpaid is False
    assert _dec(booking.amount) == Decimal("1000.00")

    confirmed = await advisor.record_confirmation(itin, node_id, supplier_ref="ABC123")
    assert str(confirmed.node_status) == "confirmed"
    assert confirmed.supplier_ref == "ABC123"

    # 4. The reconciliation invariant holds: Σ(paid lines) ⇔ Σ(booked node costs).
    report = await advisor.get_reconciliation(itin)
    assert_no_violations(money_gate_reconciles(report))
    assert report.balanced is True
