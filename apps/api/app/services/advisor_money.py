"""Cross-client invoice roster — the Money screen's read (Wave F).

``GET /advisor/money`` lists every invoice across the calling advisor's roster
(newest-first, keyset-paged) with the client/trip identity each row needs to be
legible outside its itinerary, plus a per-currency position band computed with
the same per-invoice clamp as :mod:`app.services.advisor_overview`.

This closes the advisor-plan §6 follow-up ("a cross-trip invoice/booking
roster") — until now an advisor could only see money by walking into each
trip's cockpit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    Itinerary,
    Payment,
    PaymentStatus,
)
from app.services.pagination import encode_cursor


@dataclass(frozen=True, slots=True)
class MoneyRow:
    """One invoice, roster-legible."""

    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    itinerary_id: uuid.UUID
    itinerary_title: str
    label: str
    status: InvoiceStatus
    currency: str
    total: Decimal
    settled: Decimal
    issued_at: datetime | None
    due_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MoneySummaryRow:
    """One currency's roster position (issued+paid invoices only)."""

    currency: str
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal


def summarize_positions(rows: list[MoneyRow]) -> list[MoneySummaryRow]:
    """Pure per-currency rollup with the per-invoice outstanding clamp.

    Draft and void invoices are roster rows (the advisor manages them) but not
    money position — only issued/paid count, mirroring ``derive_portfolio``.
    """
    by_currency: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for row in rows:
        if row.status not in (InvoiceStatus.issued, InvoiceStatus.paid):
            continue
        invoiced, paid, outstanding = by_currency.get(
            row.currency, (Decimal("0"), Decimal("0"), Decimal("0"))
        )
        by_currency[row.currency] = (
            invoiced + row.total,
            paid + row.settled,
            outstanding + max(Decimal("0"), row.total - row.settled),
        )
    return [
        MoneySummaryRow(currency=cur, invoiced=inv, paid=paid, outstanding=out)
        for cur, (inv, paid, out) in sorted(by_currency.items())
    ]


def next_money_cursor(rows: list[MoneyRow], limit: int) -> str | None:
    if len(rows) < limit or not rows:
        return None
    last = rows[-1]
    return encode_cursor({"at": last.created_at.isoformat(), "id": str(last.id)})


async def load_advisor_money(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    limit: int,
    cursor: dict[str, object] | None = None,
    status: InvoiceStatus | None = None,
    client_id: uuid.UUID | None = None,
) -> tuple[list[MoneyRow], list[MoneySummaryRow]]:
    """One page of roster invoices + the whole-roster currency band.

    The band always reflects the full roster (not the page): the strip must not
    change as the advisor pages. Order ``(created_at DESC, id ASC)``.
    """
    scope: list[ColumnElement[bool]] = [Client.owner_id == advisor_id]
    if client_id is not None:
        scope.append(Client.id == client_id)

    settled_by_invoice = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount), 0).label("settled"),
        )
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Payment.invoice_id)
        .subquery()
    )

    def _base_stmt() -> Any:
        return (
            select(
                Invoice.id,
                Invoice.label,
                Invoice.status,
                Invoice.currency,
                Invoice.issued_at,
                Invoice.due_at,
                Invoice.created_at,
                Invoice.itinerary_id,
                Itinerary.title,
                Client.id,
                Client.full_name,
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
            .where(*scope)
            .group_by(Invoice.id, Itinerary.title, Client.id, Client.full_name)
        )

    def _to_rows(raw: Any) -> list[MoneyRow]:
        return [
            MoneyRow(
                id=inv_id,
                client_id=cid,
                client_name=client_name,
                itinerary_id=itin_id,
                itinerary_title=itin_title,
                label=label,
                status=inv_status,
                currency=currency,
                total=Decimal(total),
                settled=Decimal(settled),
                issued_at=issued_at,
                due_at=due_at,
                created_at=created_at,
            )
            for (
                inv_id,
                label,
                inv_status,
                currency,
                issued_at,
                due_at,
                created_at,
                itin_id,
                itin_title,
                cid,
                client_name,
                total,
                settled,
            ) in raw
        ]

    page_stmt = _base_stmt()
    if status is not None:
        page_stmt = page_stmt.where(Invoice.status == status)
    if cursor is not None:
        cur_at = datetime.fromisoformat(str(cursor["at"]))
        cur_id = uuid.UUID(str(cursor["id"]))
        page_stmt = page_stmt.where(
            or_(
                Invoice.created_at < cur_at,
                and_(Invoice.created_at == cur_at, Invoice.id > cur_id),
            )
        )
    page_stmt = page_stmt.order_by(Invoice.created_at.desc(), Invoice.id.asc()).limit(limit)
    rows = _to_rows((await session.execute(page_stmt)).all())

    # The currency band: whole roster, unfiltered by page/status.
    band_rows = _to_rows((await session.execute(_base_stmt())).all())
    return rows, summarize_positions(band_rows)
