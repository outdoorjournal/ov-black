"""Billing-state derivation (AGT-3) — the server-side mirror of the web
cockpit's ``reconcileBilling``.

Pure tests over :func:`app.services.billing_summary.derive_billing_state` with
in-memory ORM rows (no DB), mirroring the web's ``dashboardModel.test.ts``
cases: the remainder math, a reversed charge falling back to uninvoiced,
``per_person`` expansion, and the issued/paid rollup.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import (
    CostKind,
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Node,
    NodeStatus,
    NodeType,
    Payment,
    PaymentStatus,
)
from app.services.billing_summary import derive_billing_state
from app.services.invoices import InvoiceView

_IT = uuid.uuid4()


def _node(
    *,
    status: NodeStatus = NodeStatus.approved,
    amount: str | None = "1200.00",
    currency: str | None = "USD",
    kind: CostKind | None = CostKind.total,
    title: str = "Ryokan stay",
) -> Node:
    return Node(
        id=uuid.uuid4(),
        itinerary_id=_IT,
        type=NodeType.hotel,
        status=status,
        title=title,
        cost_amount=Decimal(amount) if amount is not None else None,
        cost_currency=currency,
        cost_kind=kind,
    )


def _invoice(status: InvoiceStatus = InvoiceStatus.issued, currency: str = "USD") -> Invoice:
    return Invoice(
        id=uuid.uuid4(),
        itinerary_id=_IT,
        label="Invoice",
        status=status,
        currency=currency,
        created_at=datetime.now(UTC),
    )


def _charge(
    invoice: Invoice,
    *,
    node_id: uuid.UUID | None,
    amount: str,
    kind: InvoiceLineKind = InvoiceLineKind.charge,
    reverses: uuid.UUID | None = None,
) -> InvoiceLineItem:
    return InvoiceLineItem(
        id=uuid.uuid4(),
        invoice_id=invoice.id,
        node_id=node_id,
        kind=kind,
        description="",
        amount=Decimal(amount),
        currency=invoice.currency,
        reverses_line_item_id=reverses,
        created_at=datetime.now(UTC),
    )


def _payment(amount: str, status: PaymentStatus = PaymentStatus.succeeded) -> Payment:
    return Payment(
        id=uuid.uuid4(),
        status=status,
        amount=Decimal(amount),
        currency="USD",
        gateway="fake",
        gateway_reference="ref",
    )


def _view(
    invoice: Invoice, lines: list[InvoiceLineItem], payments: list[Payment] | None = None
) -> InvoiceView:
    total = sum((line.amount for line in lines), Decimal("0.00"))
    return InvoiceView(invoice=invoice, lines=lines, total=total, payments=payments or [])


def test_partially_billed_node_keeps_a_remaining_balance() -> None:
    node = _node()
    inv = _invoice()
    view = _view(inv, [_charge(inv, node_id=node.id, amount="200.00")])

    state = derive_billing_state([view], [node], {"USD": Decimal("1200.00")}, party_size=1)

    assert len(state.unbilled_nodes) == 1
    nb = state.unbilled_nodes[0]
    assert nb.effective == Decimal("1200.00")
    assert nb.charged == Decimal("200.00")
    assert nb.remaining == Decimal("1000.00")
    row = state.rows[0]
    assert row.currency == "USD"
    assert row.trip_total == Decimal("1200.00")
    assert row.invoiced == Decimal("200.00")
    assert row.uninvoiced == Decimal("1000.00")
    assert row.uninvoiced_count == 1


def test_reversed_charge_falls_back_to_uninvoiced() -> None:
    node = _node()
    inv = _invoice()
    charge = _charge(inv, node_id=node.id, amount="1200.00")
    reversal = _charge(
        inv,
        node_id=node.id,
        amount="-1200.00",
        kind=InvoiceLineKind.reversal,
        reverses=charge.id,
    )
    view = _view(inv, [charge, reversal])

    state = derive_billing_state([view], [node], {"USD": Decimal("1200.00")}, party_size=1)

    assert state.unbilled_nodes[0].charged == Decimal("0.00")
    assert state.unbilled_nodes[0].remaining == Decimal("1200.00")


def test_per_person_cost_expands_by_party_size() -> None:
    node = _node(amount="100.00", kind=CostKind.per_person)

    state = derive_billing_state([], [node], {"USD": Decimal("400.00")}, party_size=4)

    assert state.unbilled_nodes[0].effective == Decimal("400.00")
    assert state.rows[0].uninvoiced == Decimal("400.00")


def test_void_invoice_stops_covering_and_leaves_rollup() -> None:
    node = _node()
    inv = _invoice(status=InvoiceStatus.void)
    view = _view(inv, [_charge(inv, node_id=node.id, amount="1200.00")])

    state = derive_billing_state([view], [node], {"USD": Decimal("1200.00")}, party_size=1)

    # Coverage gone, rollup empty of the void invoice, and it isn't narrated.
    assert state.unbilled_nodes[0].remaining == Decimal("1200.00")
    assert state.rows[0].invoiced == Decimal("0.00")
    assert state.invoices == []


def test_paid_rollup_and_outstanding_on_issued() -> None:
    node = _node()
    paid_inv = _invoice(status=InvoiceStatus.paid)
    paid_view = _view(
        paid_inv,
        [_charge(paid_inv, node_id=node.id, amount="1200.00")],
        [_payment("1200.00")],
    )
    issued_inv = _invoice(status=InvoiceStatus.issued)
    issued_view = _view(issued_inv, [_charge(issued_inv, node_id=None, amount="300.00")])

    state = derive_billing_state(
        [paid_view, issued_view], [node], {"USD": Decimal("1200.00")}, party_size=1
    )

    row = state.rows[0]
    assert row.invoiced == Decimal("1500.00")
    assert row.paid == Decimal("1200.00")
    assert row.outstanding == Decimal("300.00")
    # The node is fully covered — nothing unbilled.
    assert state.unbilled_nodes == []
    assert row.uninvoiced == Decimal("0.00")
    # Both live invoices are narrated with their paid amounts.
    paids = {b.invoice_id: b.paid for b in state.invoices}
    assert paids[paid_inv.id] == Decimal("1200.00")
    assert paids[issued_inv.id] == Decimal("0.00")


def test_only_approved_priced_nodes_are_chargeable() -> None:
    proposed = _node(status=NodeStatus.proposed)
    costless = _node(amount=None, currency=None, kind=None)
    booked = _node(status=NodeStatus.booked)

    state = derive_billing_state([], [proposed, costless, booked], {}, party_size=1)

    assert state.unbilled_nodes == []
    assert state.rows == []
