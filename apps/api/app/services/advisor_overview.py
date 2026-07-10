"""Advisor portfolio stats — the Ops dashboard's glance band (Wave F).

One read (``GET /advisor/overview``) rolls the calling advisor's whole roster
into the numbers mission control leads with: clients by invite state, trips by
lifecycle status (plus the open fork / reconcile-pending pulse), money position
per currency, and the agent-session heartbeat for the last week.

The pure math (:func:`derive_portfolio`) is separated from the async loader
(:func:`load_advisor_overview`) — the :mod:`app.services.billing_summary` /
:mod:`app.services.awareness` split — so the clamp/rollup rules are
unit-testable without a database.

Money semantics mirror ``derive_billing_state`` at roster grain: ``invoiced``
is the signed line total of every issued/paid invoice; ``paid`` is the settled
payment total; ``outstanding`` clamps per *invoice* (``max(0, total − settled)``)
before rolling up, so one over-paid invoice never hides another's balance. The
grouped queries are per-roster, never per-itinerary — do not "simplify" this
into a ``billing_state()`` loop.

Redaction: money figures appear in the authed response (billing-endpoint
precedent) but nothing here is ever logged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentSession,
    AgentTurn,
    Client,
    ForkStatus,
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    Itinerary,
    Payment,
    PaymentStatus,
    TurnRole,
)
from app.services.display_status import display_status_expr

SESSION_WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class ClientCounts:
    total: int
    uninvited: int
    pending: int
    active: int


@dataclass(frozen=True, slots=True)
class ItineraryCounts:
    """Trunk lifecycle counts (derived buckets) + the fork/reconcile pulse.

    Buckets count official trunks only; forks appear in ``open_forks`` /
    ``reconcile_requested``.
    """

    total: int
    in_studio: int
    with_traveler: int
    approved: int
    open_forks: int
    reconcile_requested: int


@dataclass(frozen=True, slots=True)
class BillingRow:
    """One currency's roster-wide money position."""

    currency: str
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal


@dataclass(frozen=True, slots=True)
class SessionStats:
    active: int
    turns_7d: int
    errored_turns_7d: int
    avg_latency_ms_7d: int | None


@dataclass(frozen=True, slots=True)
class Portfolio:
    clients: ClientCounts
    itineraries: ItineraryCounts
    billing: list[BillingRow]
    sessions: SessionStats
    generated_at: datetime


def derive_portfolio(
    *,
    client_rows: list[tuple[str, int]],
    itinerary_rows: list[tuple[str, int]],
    open_forks: int,
    reconcile_requested: int,
    invoice_positions: list[tuple[str, Decimal, Decimal]],
    session_active: int,
    turn_stats: tuple[int, int, float | None],
    now: datetime,
) -> Portfolio:
    """Pure rollup of the grouped query rows into the response shape.

    ``client_rows`` / ``itinerary_rows`` are (bucket, count) pairs;
    ``invoice_positions`` is one row per issued/paid invoice —
    (currency, ledger_total, settled_total) — clamped and rolled up here.
    """
    clients = dict(client_rows)
    itins = dict(itinerary_rows)

    by_currency: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for currency, total, settled in invoice_positions:
        invoiced, paid, outstanding = by_currency.get(
            currency, (Decimal("0"), Decimal("0"), Decimal("0"))
        )
        by_currency[currency] = (
            invoiced + total,
            paid + settled,
            outstanding + max(Decimal("0"), total - settled),
        )
    billing = [
        BillingRow(currency=cur, invoiced=inv, paid=paid, outstanding=out)
        for cur, (inv, paid, out) in sorted(by_currency.items())
    ]

    turns, errored, avg_latency = turn_stats
    return Portfolio(
        clients=ClientCounts(
            total=sum(clients.values()),
            uninvited=clients.get("uninvited", 0),
            pending=clients.get("pending", 0),
            active=clients.get("active", 0),
        ),
        itineraries=ItineraryCounts(
            total=sum(itins.values()),
            in_studio=itins.get("in_studio", 0),
            with_traveler=itins.get("with_traveler", 0),
            approved=itins.get("approved", 0),
            open_forks=open_forks,
            reconcile_requested=reconcile_requested,
        ),
        billing=billing,
        sessions=SessionStats(
            active=session_active,
            turns_7d=turns,
            errored_turns_7d=errored,
            avg_latency_ms_7d=round(avg_latency) if avg_latency is not None else None,
        ),
        generated_at=now,
    )


async def load_advisor_overview(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    now: datetime | None = None,
) -> Portfolio:
    """Run the grouped roster queries and derive the portfolio."""
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=SESSION_WINDOW_DAYS)
    scope = Client.owner_id == advisor_id

    # ── clients by invite state (the _access_status truth table, in SQL) ──────
    access_bucket = case(
        (Client.auth_user_id.is_not(None), "active"),
        (Client.invited_at.is_not(None), "pending"),
        else_="uninvited",
    )
    client_rows = [
        (bucket, int(count))
        for bucket, count in (
            await session.execute(
                select(access_bucket, func.count(Client.id)).where(scope).group_by(access_bucket)
            )
        ).all()
    ]

    # ── trunks by derived display status + the fork/reconcile pulse ───────────
    bucket_expr = display_status_expr()
    itinerary_rows = [
        (str(bucket), int(count))
        for bucket, count in (
            await session.execute(
                select(bucket_expr, func.count(Itinerary.id))
                .join(Client, Client.id == Itinerary.client_id)
                .where(scope, Itinerary.forked_from_id.is_(None))
                .group_by(bucket_expr)
            )
        ).all()
    ]
    fork_counts = (
        await session.execute(
            select(
                func.count(Itinerary.id).filter(Itinerary.fork_status == ForkStatus.open),
                func.count(Itinerary.id).filter(Itinerary.reconcile_requested_at.is_not(None)),
            )
            .join(Client, Client.id == Itinerary.client_id)
            .where(scope)
        )
    ).one()
    open_forks, reconcile_requested = int(fork_counts[0]), int(fork_counts[1])

    # ── money position: one row per issued/paid invoice, clamped in Python ────
    settled_by_invoice = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount), 0).label("settled"),
        )
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    invoice_positions = [
        (currency, Decimal(total), Decimal(settled))
        for currency, total, settled in (
            await session.execute(
                select(
                    Invoice.currency,
                    func.coalesce(func.sum(InvoiceLineItem.amount), 0),
                    func.coalesce(func.max(settled_by_invoice.c.settled), 0),
                )
                .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
                .join(Client, Client.id == Itinerary.client_id)
                .join(InvoiceLineItem, InvoiceLineItem.invoice_id == Invoice.id, isouter=True)
                .join(
                    settled_by_invoice,
                    settled_by_invoice.c.invoice_id == Invoice.id,
                    isouter=True,
                )
                .where(
                    scope,
                    Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.paid]),
                )
                .group_by(Invoice.id, Invoice.currency)
            )
        ).all()
    ]

    # ── agent heartbeat ────────────────────────────────────────────────────────
    session_active = int(
        (
            await session.execute(
                select(func.count(AgentSession.id))
                .join(Client, Client.id == AgentSession.client_id)
                .where(
                    scope,
                    AgentSession.ended_at.is_(None),
                    AgentSession.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )
    turn_row = (
        await session.execute(
            select(
                func.count(AgentTurn.id).filter(
                    AgentTurn.role.in_([TurnRole.user, TurnRole.assistant])
                ),
                func.count(AgentTurn.id).filter(AgentTurn.error_reason.is_not(None)),
                func.avg(AgentTurn.latency_ms).filter(
                    AgentTurn.role == TurnRole.assistant,
                    AgentTurn.latency_ms.is_not(None),
                ),
            )
            .join(AgentSession, AgentSession.id == AgentTurn.session_id)
            .join(Client, Client.id == AgentSession.client_id)
            .where(scope, AgentTurn.created_at >= window_start)
        )
    ).one()
    turn_stats = (
        int(turn_row[0]),
        int(turn_row[1]),
        float(turn_row[2]) if turn_row[2] is not None else None,
    )

    return derive_portfolio(
        client_rows=client_rows,
        itinerary_rows=itinerary_rows,
        open_forks=open_forks,
        reconcile_requested=reconcile_requested,
        invoice_positions=invoice_positions,
        session_active=session_active,
        turn_stats=turn_stats,
        now=now,
    )
