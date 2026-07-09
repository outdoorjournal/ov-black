"""Roster-wide advisor activity — the merged, derived event feed (Wave F).

``GET /advisor/activity`` (and the ``/advisor/feed`` SSE tick) reads one
merged, newest-first stream of "what happened across my clients": graph
mutations, agent turns, human messages, payments, invoice lifecycle beats, and
booking beats. There is **no activity_log table and no SQL UNION view** — each
source is a small indexed query over the table that already records the event,
projected into one :class:`ActivityEvent` shape and heap-merged in Python. The
repo's derived-first taste (see awareness.py): a real event store only if it
earns it.

Pagination is keyset, total order ``(at DESC, kind ASC, source_id ASC)``.
Because ``kind`` is constant per source, the resume predicate stays a simple
per-source disjunction (see :func:`_cursor_predicate`). The same loader runs
ascending from a watermark (``after=``) for the SSE tick — strictly newer
events, oldest-first, no cursor.

Projection redaction: events carry ids, kinds, timestamps, actor kinds, titles
and (for money beats) amounts — money in an authed advisor response follows the
billing-endpoint precedent. **Never** message content, agent turn content,
fact text, or raw before/after JSONB. Nothing logged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, Text, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentSession,
    AgentTurn,
    Booking,
    Client,
    Invoice,
    InvoiceStatus,
    Itinerary,
    Message,
    Node,
    NodeHistory,
    Payment,
    Thread,
    TurnRole,
)
from app.services.pagination import encode_cursor

ActivityKind = Literal[
    "agent_turn",
    "booking_cancelled",
    "booking_confirmed",
    "booking_made",
    "invoice_created",
    "invoice_issued",
    "message_posted",
    "node_changed",
    "payment",
]

ALL_KINDS: frozenset[str] = frozenset(
    {
        "agent_turn",
        "booking_cancelled",
        "booking_confirmed",
        "booking_made",
        "invoice_created",
        "invoice_issued",
        "message_posted",
        "node_changed",
        "payment",
    }
)


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """One projected event — the only shape that leaves this module."""

    kind: ActivityKind
    at: datetime
    source_id: str
    client_id: uuid.UUID
    itinerary_id: uuid.UUID | None
    itinerary_title: str | None
    actor_kind: str | None
    title: str | None
    op: str | None
    status_before: str | None
    status_after: str | None
    amount: Decimal | None
    currency: str | None
    ref_id: uuid.UUID | None


def sort_key_desc(e: ActivityEvent) -> tuple[float, str, str]:
    """The feed's total order, descending time: (at DESC, kind ASC, source_id ASC)."""
    return (-e.at.timestamp(), e.kind, e.source_id)


def next_cursor_for(events: list[ActivityEvent], limit: int) -> str | None:
    """Opaque resume token — only when the page filled (a short page is the end)."""
    if len(events) < limit or not events:
        return None
    last = events[-1]
    return encode_cursor(
        {"at": last.at.isoformat(), "kind": last.kind, "source_id": last.source_id}
    )


def _cursor_predicate(
    kind: str,
    at_col: Any,
    id_col: Any,
    cursor: dict[str, object],
) -> Any:
    """Rows strictly after the cursor position in (at DESC, kind ASC, id ASC) order.

    ``kind`` is constant per source, so the three-way tie-break collapses:
    same kind → same-instant rows tie-break on id; an alphabetically earlier
    kind sorts *before* ours at the same instant, so we must exclude the tie.
    """
    cur_at = datetime.fromisoformat(str(cursor["at"]))
    cur_kind = str(cursor["kind"])
    cur_id = str(cursor["source_id"])
    if kind == cur_kind:
        return or_(at_col < cur_at, and_(at_col == cur_at, id_col > cur_id))
    if kind > cur_kind:
        return at_col <= cur_at
    return at_col < cur_at


async def load_advisor_activity(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    limit: int,
    cursor: dict[str, object] | None = None,
    after: datetime | None = None,
    client_id: uuid.UUID | None = None,
    itinerary_id: uuid.UUID | None = None,
    kinds: frozenset[str] | None = None,
) -> list[ActivityEvent]:
    """Load one merged page of advisor activity.

    Two modes sharing every query:
    - **paging** (default / ``cursor=``): newest-first, resume below the cursor.
    - **tick** (``after=``): strictly newer than the watermark, oldest-first —
      the SSE poll primitive. ``cursor`` and ``after`` are mutually exclusive.

    Sources excluded by ``kinds`` are never queried (the feed stays lazy).
    """
    if cursor is not None and after is not None:  # pragma: no cover — router-guarded
        raise ValueError("cursor and after are mutually exclusive")
    wanted = ALL_KINDS if kinds is None else kinds

    scope: list[ColumnElement[bool]] = [Client.owner_id == advisor_id]
    if client_id is not None:
        scope.append(Client.id == client_id)

    def _windowed(
        kind: str,
        stmt: Select[Any],
        at_col: Any,
        id_col: Any,
    ) -> Select[Any]:
        if cursor is not None:
            stmt = stmt.where(_cursor_predicate(kind, at_col, id_col, cursor))
            return stmt.order_by(at_col.desc(), id_col.asc()).limit(limit)
        if after is not None:
            stmt = stmt.where(at_col > after)
            return stmt.order_by(at_col.asc(), id_col.asc()).limit(limit)
        return stmt.order_by(at_col.desc(), id_col.asc()).limit(limit)

    events: list[ActivityEvent] = []
    # Column handles vary in nullability across sources — keep them loose.
    at_col: Any
    id_col: Any

    # ── graph mutations ────────────────────────────────────────────────────────
    if "node_changed" in wanted:
        at_col = NodeHistory.occurred_at
        id_col = NodeHistory.id.cast(Text)
        stmt = (
            select(
                NodeHistory.id,
                NodeHistory.node_id,
                NodeHistory.itinerary_id,
                NodeHistory.op,
                NodeHistory.actor_kind,
                NodeHistory.before,
                NodeHistory.after,
                NodeHistory.occurred_at,
                Itinerary.client_id,
                Itinerary.title,
            )
            .join(Itinerary, Itinerary.id == NodeHistory.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope)
        )
        if itinerary_id is not None:
            stmt = stmt.where(NodeHistory.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed("node_changed", stmt, at_col, id_col))).all()
        for hid, node_id, itin_id, op, actor_kind, before, after_, at, cid, itin_title in rows:
            before = before or {}
            after_ = after_ or {}
            events.append(
                ActivityEvent(
                    kind="node_changed",
                    at=at,
                    source_id=str(hid),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=itin_title,
                    actor_kind=actor_kind,
                    title=after_.get("title") or before.get("title"),
                    op=op,
                    status_before=before.get("status"),
                    status_after=after_.get("status"),
                    amount=None,
                    currency=None,
                    ref_id=node_id,
                )
            )

    # ── agent turns (assistant only; never content) ────────────────────────────
    if "agent_turn" in wanted:
        at_col = AgentTurn.created_at
        id_col = AgentTurn.id.cast(Text)
        stmt = (
            select(
                AgentTurn.id,
                AgentTurn.created_at,
                AgentTurn.actor_kind,
                AgentSession.id,
                AgentSession.itinerary_id,
                AgentSession.client_id,
            )
            .join(AgentSession, AgentSession.id == AgentTurn.session_id)
            .join(Client, Client.id == AgentSession.client_id)
            .where(*scope, AgentTurn.role == TurnRole.assistant)
        )
        if itinerary_id is not None:
            stmt = stmt.where(AgentSession.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed("agent_turn", stmt, at_col, id_col))).all()
        for tid, at, actor_kind, sid, itin_id, cid in rows:
            events.append(
                ActivityEvent(
                    kind="agent_turn",
                    at=at,
                    source_id=str(tid),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=None,
                    actor_kind=actor_kind,
                    title=None,
                    op=None,
                    status_before=None,
                    status_after=None,
                    amount=None,
                    currency=None,
                    ref_id=sid,
                )
            )

    # ── human-thread messages (never content) ──────────────────────────────────
    if "message_posted" in wanted:
        at_col = Message.created_at
        id_col = Message.id.cast(Text)
        stmt = (
            select(
                Message.id,
                Message.created_at,
                Message.author_kind,
                Thread.id,
                Thread.itinerary_id,
                Thread.client_id,
            )
            .join(Thread, Thread.id == Message.thread_id)
            .join(Client, Client.id == Thread.client_id)
            .where(*scope, Message.removed_at.is_(None))
        )
        if itinerary_id is not None:
            stmt = stmt.where(Thread.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed("message_posted", stmt, at_col, id_col))).all()
        for mid, at, author_kind, thread_id, itin_id, cid in rows:
            events.append(
                ActivityEvent(
                    kind="message_posted",
                    at=at,
                    source_id=str(mid),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=None,
                    actor_kind=author_kind.value,
                    title=None,
                    op=None,
                    status_before=None,
                    status_after=None,
                    amount=None,
                    currency=None,
                    ref_id=thread_id,
                )
            )

    # ── payments ───────────────────────────────────────────────────────────────
    if "payment" in wanted:
        at_col = Payment.created_at
        id_col = Payment.id.cast(Text)
        stmt = (
            select(
                Payment.id,
                Payment.created_at,
                Payment.status,
                Payment.amount,
                Payment.currency,
                Invoice.id,
                Invoice.label,
                Invoice.itinerary_id,
                Itinerary.client_id,
                Itinerary.title,
            )
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope)
        )
        if itinerary_id is not None:
            stmt = stmt.where(Invoice.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed("payment", stmt, at_col, id_col))).all()
        for pid, at, status, amount, currency, inv_id, label, itin_id, cid, itin_title in rows:
            events.append(
                ActivityEvent(
                    kind="payment",
                    at=at,
                    source_id=str(pid),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=itin_title,
                    actor_kind=None,
                    title=label,
                    op=status.value,
                    status_before=None,
                    status_after=None,
                    amount=amount,
                    currency=currency,
                    ref_id=inv_id,
                )
            )

    # ── invoice lifecycle beats ────────────────────────────────────────────────
    for inv_kind, inv_at in (
        ("invoice_created", Invoice.created_at),
        ("invoice_issued", Invoice.issued_at),
    ):
        if inv_kind not in wanted:
            continue
        at_col = inv_at
        id_col = Invoice.id.cast(Text)
        stmt = (
            select(
                Invoice.id,
                inv_at,
                Invoice.label,
                Invoice.status,
                Invoice.currency,
                Invoice.itinerary_id,
                Itinerary.client_id,
                Itinerary.title,
            )
            .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope, Invoice.status != InvoiceStatus.void)
        )
        if inv_kind == "invoice_issued":
            stmt = stmt.where(Invoice.issued_at.is_not(None))
        if itinerary_id is not None:
            stmt = stmt.where(Invoice.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed(inv_kind, stmt, at_col, id_col))).all()
        for inv_id, at, label, status, currency, itin_id, cid, itin_title in rows:
            events.append(
                ActivityEvent(
                    kind=inv_kind,  # type: ignore[arg-type]
                    at=at,
                    source_id=str(inv_id),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=itin_title,
                    actor_kind=None,
                    title=label,
                    op=status.value,
                    status_before=None,
                    status_after=None,
                    amount=None,
                    currency=currency,
                    ref_id=inv_id,
                )
            )

    # ── booking beats: made / confirmed / cancelled off one table ──────────────
    for bk_kind, bk_at in (
        ("booking_made", Booking.booked_at),
        ("booking_confirmed", Booking.confirmed_at),
        ("booking_cancelled", Booking.cancelled_at),
    ):
        if bk_kind not in wanted:
            continue
        at_col = bk_at
        id_col = Booking.id.cast(Text)
        stmt = (
            select(
                Booking.id,
                bk_at,
                Booking.amount,
                Booking.currency,
                Booking.node_id,
                Node.title,
                Node.itinerary_id,
                Itinerary.client_id,
                Itinerary.title,
            )
            .join(Node, Node.id == Booking.node_id)
            .join(Itinerary, Itinerary.id == Node.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope, bk_at.is_not(None))
        )
        if itinerary_id is not None:
            stmt = stmt.where(Node.itinerary_id == itinerary_id)
        rows = (await session.execute(_windowed(bk_kind, stmt, at_col, id_col))).all()
        for bid, at, amount, currency, node_id, node_title, itin_id, cid, itin_title in rows:
            events.append(
                ActivityEvent(
                    kind=bk_kind,  # type: ignore[arg-type]
                    at=at,
                    source_id=str(bid),
                    client_id=cid,
                    itinerary_id=itin_id,
                    itinerary_title=itin_title,
                    actor_kind=None,
                    title=node_title,
                    op=None,
                    status_before=None,
                    status_after=None,
                    amount=amount,
                    currency=currency,
                    ref_id=node_id,
                )
            )

    if after is not None:
        events.sort(key=lambda e: (e.at.timestamp(), e.kind, e.source_id))
    else:
        events.sort(key=sort_key_desc)
    return events[:limit]
