"""Deposit schedule + quick-action invoice seeding (doc/thoughts.md §5).

Two advisor conveniences over the itinerary's chargeable nodes:

- **Deposit** — a draft invoice that captures the upfront hold. The schedule is
  deliberately simple for now (it will grow backend business logic later): a
  **flight** deposits **100%** of its cost, everything else **20%**. Per-node the
  amount is the deposit level minus whatever's already been billed.
- **Final** — a draft that bills each chargeable node's whole remaining balance.

Both reuse the native, amount-aware ledger: one draft invoice may hold several
NATIVE currencies (0050), each node line carries its own, and the money gate stays
native. The deposit level and the "what's left" both come from
:func:`app.services.billing_summary.billing_state` so this never re-derives cost.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, InvoiceLineKind, NodeType
from app.services import billing_summary as billing_summary_svc
from app.services import invoices as invoices_svc
from app.services.billing_summary import UnbilledNode
from app.services.itineraries import ActorContext, ItineraryError, ItineraryOutcome

_ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")

# The MVP deposit schedule (doc/thoughts.md §3): flights are held in full, all other
# inventory at a fifth. A single knob today; real business logic later.
_FLIGHT_DEPOSIT = Decimal("1.00")
_DEFAULT_DEPOSIT = Decimal("0.20")


def deposit_fraction(node_type: NodeType) -> Decimal:
    """The fraction of a node's effective cost taken as deposit."""
    return _FLIGHT_DEPOSIT if node_type is NodeType.flight else _DEFAULT_DEPOSIT


def deposit_due(effective: Decimal, node_type: NodeType) -> Decimal:
    """The deposit level for a node — ``effective × fraction``, rounded to cents.

    The total that SHOULD be on deposit; the additional charge is this minus what's
    already billed (see :func:`_deposit_amount`)."""
    return (effective * deposit_fraction(node_type)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _deposit_amount(node: UnbilledNode) -> Decimal:
    """The additional deposit charge for a node — the deposit level minus what's
    already billed, floored at 0 and never exceeding the remaining balance."""
    due = deposit_due(node.effective, node.node_type)
    return max(_ZERO, min(due - node.charged, node.remaining))


def _err(detail: str) -> ItineraryError:
    return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail=detail)


def _dominant_currency(targets: list[tuple[UnbilledNode, Decimal]]) -> str:
    """The currency carrying the largest share — the invoice's ``currency`` default
    (a soft home/label field now that lines are multi-currency, 0050)."""
    totals: dict[str, Decimal] = {}
    for node, amount in targets:
        totals[node.currency] = totals.get(node.currency, _ZERO) + amount
    return max(totals, key=lambda c: totals[c])


async def _seed_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    label: str,
    targets: list[tuple[UnbilledNode, Decimal]],
    no_targets_error: str,
) -> Invoice | ItineraryError:
    """Create one draft invoice and post a native charge line per (node, amount)."""
    priced = [(node, amount) for node, amount in targets if amount > _ZERO]
    if not priced:
        return _err(no_targets_error)

    invoice = await invoices_svc.create_invoice(
        session,
        actor,
        itinerary_id=itinerary_id,
        label=label,
        currency=_dominant_currency(priced),
    )
    if isinstance(invoice, ItineraryError):
        return invoice

    for node, amount in priced:
        line = await invoices_svc.add_line_item(
            session,
            actor,
            invoice_id=invoice.id,
            description=node.title,
            amount=amount.quantize(_CENTS, rounding=ROUND_HALF_UP),
            currency=node.currency,
            kind=InvoiceLineKind.charge,
            node_id=node.node_id,
        )
        if isinstance(line, ItineraryError):
            return line
    return invoice


async def seed_deposit_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Invoice | ItineraryError:
    """Draft a "Deposit" invoice: 100% of flights, 20% of everything else, over
    every chargeable node with a deposit still owed (doc/thoughts.md §5a)."""
    state = await billing_summary_svc.billing_state(session, itinerary_id)
    targets = [(node, _deposit_amount(node)) for node in state.unbilled_nodes]
    return await _seed_invoice(
        session,
        actor,
        itinerary_id=itinerary_id,
        label="Deposit",
        targets=targets,
        no_targets_error="nothing_to_deposit",
    )


async def seed_final_invoice(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Invoice | ItineraryError:
    """Draft a "Balance" invoice billing each chargeable node's whole remaining
    balance (doc/thoughts.md §5b)."""
    state = await billing_summary_svc.billing_state(session, itinerary_id)
    targets = [(node, node.remaining) for node in state.unbilled_nodes]
    return await _seed_invoice(
        session,
        actor,
        itinerary_id=itinerary_id,
        label="Balance",
        targets=targets,
        no_targets_error="nothing_to_bill",
    )
