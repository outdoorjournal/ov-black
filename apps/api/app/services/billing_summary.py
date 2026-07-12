"""Itinerary-wide billing state — trip total vs invoiced/paid/outstanding, plus
the per-node uninvoiced remainder.

Server-side mirror of the web cockpit's ``reconcileBilling``
(``apps/web/app/itinerary/[id]/_shell/dashboardModel.ts``) so the agent's money
awareness (AGT-3 ``get_billing_state``) and the per-turn graph digest (AGT-2)
read the same money truth the advisor's reconciliation strip shows. The pure
derivation (:func:`derive_billing_state`) is separated from the loader
(:func:`billing_state`) so the math is unit-testable without a database, the
same split the web keeps between ``dashboardModel`` and its stores.

Semantics mirrored exactly from the web model:

- **Chargeable** = an ``approved`` node carrying the cost pair (the bookable
  lifecycle entry point — ideas/proposals aren't billable yet, booked nodes
  were already paid through the money gate).
- **Coverage** = Σ of a node's ``charge`` lines across every non-void invoice,
  excluding charges a ``reversal`` line has cancelled.
- **Effective cost** = ``per_person`` × party size, everything else at face
  value (:func:`app.services.node_cost.effective_node_cost` — the single
  billing truth shared with invoice lines and the money gate).
- **Invoiced / paid / outstanding** roll up over issued + paid invoices only
  (drafts are advisor-in-progress, void drops out everywhere).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InvoiceLineKind,
    InvoiceStatus,
    Node,
    NodeStatus,
    NodeType,
)
from app.services import invoices as invoices_svc
from app.services.invoices import InvoiceView
from app.services.node_cost import (
    effective_node_cost,
    resolve_party_size,
    sum_node_costs,
)

_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class UnbilledNode:
    """A chargeable node whose effective cost is not yet fully billed."""

    node_id: uuid.UUID
    title: str
    currency: str
    effective: Decimal
    charged: Decimal
    remaining: Decimal
    # Drives the deposit schedule (finance_rules): flights deposit 100%, else 20%.
    node_type: NodeType


@dataclass(frozen=True, slots=True)
class BillingCurrencyRow:
    """One currency's reconciliation: the trip's money truth at a glance."""

    currency: str
    trip_total: Decimal
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal
    uninvoiced: Decimal
    uninvoiced_count: int


@dataclass(frozen=True, slots=True)
class InvoiceBrief:
    """One invoice's headline for narration (no ledger detail)."""

    invoice_id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    total: Decimal
    paid: Decimal


@dataclass(frozen=True, slots=True)
class BillingState:
    rows: list[BillingCurrencyRow]
    unbilled_nodes: list[UnbilledNode]
    invoices: list[InvoiceBrief]


def _charged_by_node(views: Sequence[InvoiceView]) -> dict[uuid.UUID, Decimal]:
    """node_id → Σ its covering charge amounts across every non-void invoice.

    A charge some reversal line cancels no longer covers (mirrors the web
    ``coverageByNode`` and the service-side ``_node_charged_total`` exactly).
    """
    charged: dict[uuid.UUID, Decimal] = {}
    for view in views:
        if view.invoice.status is InvoiceStatus.void:
            continue
        reversed_ids = {
            line.reverses_line_item_id
            for line in view.lines
            if line.reverses_line_item_id is not None
        }
        for line in view.lines:
            if line.kind is not InvoiceLineKind.charge or line.node_id is None:
                continue
            if line.id in reversed_ids:
                continue
            charged[line.node_id] = charged.get(line.node_id, _ZERO) + line.amount
    return charged


def _is_chargeable(node: Node) -> bool:
    return (
        node.status is NodeStatus.approved
        and node.cost_amount is not None
        and bool(node.cost_currency)
    )


def derive_billing_state(
    views: Sequence[InvoiceView],
    nodes: Sequence[Node],
    totals: dict[str, Decimal],
    party_size: int,
) -> BillingState:
    """Pure reconciliation over already-loaded rows (no I/O)."""
    charged = _charged_by_node(views)

    unbilled: list[UnbilledNode] = []
    for node in nodes:
        if not _is_chargeable(node):
            continue
        assert node.cost_amount is not None and node.cost_currency is not None
        effective = effective_node_cost(node.cost_amount, node.cost_kind, party_size)
        billed = charged.get(node.id, _ZERO)
        remaining = effective - billed
        if remaining > _ZERO:
            unbilled.append(
                UnbilledNode(
                    node_id=node.id,
                    title=node.title,
                    currency=node.cost_currency,
                    effective=effective,
                    charged=billed,
                    remaining=remaining,
                    node_type=node.type,
                )
            )

    # Per-currency rollup over issued + paid invoices (drafts pending, void out).
    # Keyed on each line's NATIVE currency via ``view.subtotals`` (an invoice may hold
    # several since 0050). Payments settle the WHOLE invoice in the settlement
    # currency, so "paid"/"outstanding" are all-or-nothing per invoice: a paid
    # invoice's native subtotals count as paid, an issued (unpaid) one's as
    # outstanding — never mixing the settlement-denominated Payment amounts into a
    # native bucket.
    invoiced_by_ccy: dict[str, Decimal] = {}
    paid_by_ccy: dict[str, Decimal] = {}
    outstanding_by_ccy: dict[str, Decimal] = {}
    for view in views:
        status = view.invoice.status
        if status not in (InvoiceStatus.issued, InvoiceStatus.paid):
            continue
        for ccy, subtotal in view.subtotals.items():
            invoiced_by_ccy[ccy] = invoiced_by_ccy.get(ccy, _ZERO) + subtotal
            if status is InvoiceStatus.paid:
                paid_by_ccy[ccy] = paid_by_ccy.get(ccy, _ZERO) + subtotal
            else:  # issued (unpaid) — the whole native subtotal is outstanding
                outstanding_by_ccy[ccy] = outstanding_by_ccy.get(ccy, _ZERO) + subtotal

    currencies = sorted(set(totals) | set(invoiced_by_ccy) | {n.currency for n in unbilled})
    rows = [
        BillingCurrencyRow(
            currency=ccy,
            trip_total=totals.get(ccy, _ZERO),
            invoiced=invoiced_by_ccy.get(ccy, _ZERO),
            paid=paid_by_ccy.get(ccy, _ZERO),
            outstanding=outstanding_by_ccy.get(ccy, _ZERO),
            uninvoiced=sum((n.remaining for n in unbilled if n.currency == ccy), _ZERO),
            uninvoiced_count=sum(1 for n in unbilled if n.currency == ccy),
        )
        for ccy in currencies
    ]

    briefs = [
        InvoiceBrief(
            invoice_id=view.invoice.id,
            label=view.invoice.label,
            status=view.invoice.status,
            currency=view.invoice.currency,
            total=view.total,
            # Whole-invoice payment: paid-in-full or not at all (0050).
            paid=view.total if view.invoice.status is InvoiceStatus.paid else _ZERO,
        )
        for view in views
        if view.invoice.status is not InvoiceStatus.void
    ]

    return BillingState(rows=rows, unbilled_nodes=unbilled, invoices=briefs)


async def billing_state(session: AsyncSession, itinerary_id: uuid.UUID) -> BillingState:
    """Load + derive the itinerary's billing state (the async seam routes use)."""
    views = await invoices_svc.list_invoices(session, itinerary_id)
    nodes = (
        (
            await session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary_id,
                    Node.is_selected_alt.is_(True),
                    Node.deleted_at.is_(None),
                    Node.status != NodeStatus.discarded,
                )
            )
        )
        .scalars()
        .all()
    )
    totals = await sum_node_costs(session, itinerary_id)
    party_size = await resolve_party_size(session, itinerary_id)
    return derive_billing_state(views, list(nodes), totals, party_size)
