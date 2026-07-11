"""First-class node cost — derivation from inventory + per-itinerary sums.

M002/B4 promotes a bookable node's price from a free-text ``metadata``
string to the first-class ``nodes.cost_amount`` / ``cost_currency`` /
``cost_kind`` columns (migration 0016, decision D-COST). This module owns the
two cost concerns that aren't graph-CRUD:

- :func:`cost_from_inventory_item` — map a normalized ``InventoryItem``'s
  ``price`` to the (amount, currency, kind) a node stores. Called at the
  ``POST /itinerary/{id}/nodes/from-inventory`` seam so a Duffel flight or a
  Ratehawk hotel lands with a queryable numeric cost, not a snapshot string.
- :func:`sum_node_costs` — total an itinerary's node costs, grouped by
  currency. The M005 money gate sums booked-node costs through this helper and
  reconciles them against paid invoice lines.

Deliberately separate from :mod:`app.services.card_mapping` (which shapes the
render-time card attrs) so cost is modeled independently of presentation, and
from :mod:`app.services.itineraries` so the graph service stays free of
inventory-schema imports.

A flight's amount is a REPRICEABLE quote (D024): it's the agreed cost at
proposal, valid only until the offer expires. The transient offer + its refresh
history live in ``node_offers`` (M005); ``cost_amount`` is the static snapshot
the money gate re-prices before booking.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import NamedTuple

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.schemas import FlightItem, HotelItem, InventoryItem
from app.models import CostKind, Node, NodeStatus, Party, PartyMember, Traveler

# Whole-booking providers quote one total for the node (a Duffel offer covers
# every passenger on the request; a Ratehawk rate is the whole stay). Anything
# else (OV experiences quote a per-person ``minPrice``) is treated per traveler.
_TOTAL_PRICED_KINDS = (FlightItem, HotelItem)

_CENTS = Decimal("0.01")


class NodeCost(NamedTuple):
    """The first-class cost triple a node carries (all three or none)."""

    amount: Decimal
    currency: str
    kind: CostKind


def _to_amount(value: float | int | None) -> Decimal | None:
    """Coerce a provider's major-unit float to a 2dp ``Decimal``, or ``None``.

    Goes through ``str`` so a float like ``1234.1`` doesn't pick up binary
    representation noise before quantizing. Non-finite / unparseable values
    (NaN, inf) yield ``None`` rather than poisoning the cost column.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not dec.is_finite():
        return None
    return dec.quantize(_CENTS, rounding=ROUND_HALF_UP)


def cost_from_inventory_item(item: InventoryItem) -> NodeCost | None:
    """Derive a node's (amount, currency, kind) from an inventory item's price.

    Uses the item's headline figure (``price.amount_min``, falling back to
    ``amount_max``) and ``price.currency``. Returns ``None`` when the item has
    no priceable amount *and* currency together — a meal from Google Places
    (no bookable amount) or a price-less idea simply carries no cost, and the
    ``nodes_cost_amount_currency_together`` CHECK requires both halves.

    ``kind`` is ``total`` for whole-booking providers (flights, hotels) and
    ``per_person`` otherwise, matching how each provider quotes its price.
    """
    price = item.price
    if price is None:
        return None
    amount = _to_amount(price.amount_min)
    if amount is None:
        amount = _to_amount(price.amount_max)
    currency = price.currency if isinstance(price.currency, str) and price.currency else None
    if amount is None or currency is None:
        return None
    kind = CostKind.total if isinstance(item, _TOTAL_PRICED_KINDS) else CostKind.per_person
    return NodeCost(amount=amount, currency=currency, kind=kind)


def effective_node_cost(amount: Decimal, kind: CostKind | None, party_size: int) -> Decimal:
    """The billable amount for a node: ``per_person`` × party size, else face value.

    A ``per_person`` quote (an OV experience's ``minPrice``) is multiplied by the
    number of travelers; ``total`` (a flight offer, a whole-stay hotel rate) and an
    unset ``kind`` bill as quoted. ``party_size`` is floored at 1 so a missing
    party never zeroes a charge. This is the single source of truth shared by
    invoice-line assembly, the booked amount, and the money-gate sums so they
    cannot drift (a mismatch would permanently break the reconciliation invariant).
    """
    if kind is CostKind.per_person:
        return amount * max(party_size, 1)
    return amount


async def resolve_party_size(session: AsyncSession, itinerary_id: uuid.UUID) -> int:
    """The itinerary's effective head-count for per-person cost expansion.

    Resolution order: (1) the sum of any advisor-set ``parties.member_count`` —
    an explicit total head-count; (2) else the count of named *companion*
    ``travelers`` rows **plus one** for the account holder, who is the party's
    implicit floor and never a companion row. This is why a solo trip with an
    empty edge still bills at ``1``, and why the dashboard can read "Just you"
    off zero travelers while a per-person cost still counts the traveller
    themselves. A companion is any ``travelers`` row not linked to the primary
    ``party_member`` — so an account holder ever explicitly seated on the edge
    is counted once (via the +1), not twice. Per-node ``node_parties`` precision
    is deliberately deferred — a node bills for the whole trip party.
    """
    explicit_total, explicit_count = (
        await session.execute(
            select(func.sum(Party.member_count), func.count(Party.member_count)).where(
                Party.itinerary_id == itinerary_id
            )
        )
    ).one()
    if explicit_count and explicit_total:
        return max(int(explicit_total), 1)

    companion_count = (
        await session.execute(
            select(func.count(Traveler.id))
            .join(Party, Party.id == Traveler.party_id)
            .outerjoin(PartyMember, PartyMember.id == Traveler.party_member_id)
            .where(
                Party.itinerary_id == itinerary_id,
                or_(PartyMember.id.is_(None), PartyMember.is_primary.is_(False)),
            )
        )
    ).scalar_one()
    return int(companion_count) + 1


async def sum_node_costs(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    statuses: Collection[NodeStatus] | None = None,
) -> dict[str, Decimal]:
    """Sum an itinerary's node costs, grouped by currency.

    Returns ``{currency: total}`` over the itinerary's priced nodes, summed in
    each native currency — cross-currency conversion to one display currency is a
    read-side concern deferred per D-COST. ``per_person`` amounts are expanded by
    the itinerary's party size (see :func:`resolve_party_size`) so the money-gate
    booked-sum matches the per-person charge lines billed for the same nodes; a
    mismatch would permanently break the reconciliation invariant. An itinerary
    with no priced nodes yields ``{}``.

    Only *selected* branches participate (``is_selected_alt`` is true) so a
    deselected alternative never double-counts. By default ``discarded`` nodes
    are excluded; pass ``statuses`` to restrict to specific lifecycle states
    (e.g. the money gate sums ``{booked, confirmed}``).
    """
    conditions = [
        Node.itinerary_id == itinerary_id,
        Node.cost_amount.isnot(None),
        Node.cost_currency.isnot(None),
        Node.is_selected_alt.is_(True),
        Node.deleted_at.is_(None),
    ]
    if statuses is not None:
        conditions.append(Node.status.in_(list(statuses)))
    else:
        conditions.append(Node.status != NodeStatus.discarded)

    party_size = await resolve_party_size(session, itinerary_id)
    amount_expr = case(
        (Node.cost_kind == CostKind.per_person, Node.cost_amount * party_size),
        else_=Node.cost_amount,
    )
    stmt = (
        select(Node.cost_currency, func.sum(amount_expr))
        .where(*conditions)
        .group_by(Node.cost_currency)
    )
    rows = (await session.execute(stmt)).all()
    return {
        currency: total for currency, total in rows if currency is not None and total is not None
    }
