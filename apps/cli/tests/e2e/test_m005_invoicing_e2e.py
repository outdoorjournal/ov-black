"""Pillar 6 — Invoicing & payment over the wire (M005 / I1 + I2).

Demo-script stage 6 (mvp.md §7): *"Advisor assembles an invoice from approved
bookable nodes, layers a discount, issues it; the traveler pays and the invoice
flips to paid."*

Drives the whole I1 + I2 contract against a live stack with the real SDK the UI
uses:
  - advisor prices an approved bookable node, then charges it onto a fresh
    invoice (charge-from-node = node's B4 cost);
  - a signed discount line nets the total down; voiding it appends a reversal
    that nets it back (the journal-entry void);
  - the invoice issues and is paid with a tokenized nonce; it flips to ``paid``
    and a ``succeeded`` payment is recorded.

The pay step uses ``fake-valid-nonce`` — accepted by both the local Fake gateway
(no credentials) and the Braintree sandbox — so it runs without secrets. If the
target has no gateway wired (``payments_unconfigured``), the pay step self-skips
rather than false-failing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from ovb.errors import ApiError
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e

_BOOKABLE = {"flight", "hotel", "experience", "meal"}
_FIRMED = {"approved", "booked", "confirmed"}


def _bookable_node(graph: Any) -> Any | None:
    return next((n for n in graph.nodes if str(n.type) in _BOOKABLE), None)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


async def _approved_priced_node(advisor: Ovb, itin: str, *, amount: str, currency: str) -> str:
    """Make a bookable node approved + priced; return its id.

    Sets the cost while the node is pre-firmed (the G1 gate forbids field edits on
    a firmed node), then approves it — mirroring "invoice the approved bookables".
    """
    node = _bookable_node(await advisor.get_graph(itin))
    if node is None:
        pytest.skip("no bookable node in the seeded itinerary to invoice")
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


async def test_advisor_invoices_and_collects_payment(advisor: Ovb, built_itinerary: str) -> None:
    itin = built_itinerary
    node_id = await _approved_priced_node(advisor, itin, amount="1000.00", currency="USD")

    # Assemble: a charge from the node's cost + an elderly discount.
    invoice = await advisor.create_invoice(itin, label="Deposit", currency="USD")
    invoice_id = str(invoice.id)
    assert str(invoice.status) == "draft"

    charge = await advisor.add_invoice_line(invoice_id, node_id=node_id)
    assert str(charge.kind) == "charge"
    assert _dec(charge.amount) == Decimal("1000.00")

    discount = await advisor.add_invoice_line(
        invoice_id,
        kind="discount",
        description="Elderly discount",
        amount="-250.00",
        currency="USD",
    )

    got = await advisor.get_invoice(invoice_id)
    assert _dec(got.total) == Decimal("750.00")  # 1000 - 250

    # Void the discount → reversal nets it back to 1000.
    reversal = await advisor.void_invoice_line(invoice_id, str(discount.id))
    assert str(reversal.kind) == "reversal"
    got = await advisor.get_invoice(invoice_id)
    assert _dec(got.total) == Decimal("1000.00")

    # Issue, then pay with a tokenized nonce.
    issued = await advisor.issue_invoice(invoice_id)
    assert str(issued.status) == "issued"

    try:
        paid = await advisor.pay_invoice(invoice_id, payment_method_nonce="fake-valid-nonce")
    except ApiError as exc:
        if exc.detail == "payments_unconfigured":
            pytest.skip("no payment gateway wired on this target (prod without keys)")
        raise

    assert str(paid.status) == "paid"
    succeeded = [p for p in paid.payments if str(p.status) == "succeeded"]
    assert len(succeeded) == 1
    assert _dec(succeeded[0].amount) == Decimal("1000.00")
    assert succeeded[0].gateway_reference  # our cross-reference key is recorded
