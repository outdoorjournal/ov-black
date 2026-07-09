"""Advisor awareness feed — "what wants my attention", derived, no new table.

ADV-14 (Wave D). When an advisor returns to the Command Center, nothing tells
them *which* clients are waiting on them — a change request lives inside one
fork's Studio, approvals and payments require walking into each trip. This
service reads four already-persisted signals and rolls them up per client so the
roster can badge the ones that need a hand and the client page can show a
"what's happened" strip.

The four signals split into two tiers:

- **Actionable (open-state)** — self-clear when the advisor does the work, so
  they drive the roster badge without ever going stale:
    - ``changes_requested`` — an open reconcile: the traveler asked staff to
      merge a fork's changes back (``itineraries.reconcile_requested_at``);
      cleared on merge/withdraw.
    - ``unread_messages`` — human-thread messages authored by someone other than
      the advisor, newer than the advisor's ``thread_participants.last_read_at``;
      cleared when the advisor opens the thread (:func:`messaging.list_messages`
      stamps the read watermark).
- **Recent activity (event-style, rolling window)** — informational context for
  the per-client strip only, *not* the badge (no persisted "last looked"
  watermark yet — see the plan's earns-it follow-up):
    - ``traveler_approved`` — the traveler approved cards in the last
      :data:`RECENT_WINDOW_DAYS` days (``node_history`` status → approved).
    - ``payment_received`` — a payment succeeded in the last window.

Everything is scoped to the calling advisor's clients (``clients.owner_id``).
The pure rollup (:func:`build_client_attention`) is separated from the async
loader (:func:`load_advisor_attention`) so the tiering math is unit-testable
without a database — the same split :mod:`app.services.billing_summary` and
:mod:`app.services.graph_digest` keep.

Redaction: only ids, counts, titles, and timestamps flow through here — never
message content, fact text, or money figures. Nothing logged.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Invoice,
    Itinerary,
    Message,
    NodeHistory,
    Payment,
    PaymentStatus,
    Thread,
    ThreadActorKind,
    ThreadParticipant,
)

# Rolling window for the event-style (non-open-state) signals. Open-state
# signals (reconcile / unread) carry no window — they show while they're open.
RECENT_WINDOW_DAYS = 14

AttentionKind = Literal[
    "changes_requested",
    "unread_messages",
    "traveler_approved",
    "payment_received",
]

# The open-state signals — these and only these light the roster badge, because
# they clear themselves when the advisor acts. Recent-activity signals are strip
# context, so a glanced-at client doesn't keep a stale count forever.
_ACTIONABLE_KINDS: frozenset[str] = frozenset({"changes_requested", "unread_messages"})


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One signal on one (client, itinerary) — a row in the per-client strip.

    ``itinerary_id`` is None for a basecamp-scoped thread's unread (a client-wide
    conversation not tied to a single trip); every other kind is trip-scoped.
    """

    kind: AttentionKind
    itinerary_id: uuid.UUID | None
    itinerary_title: str | None
    count: int
    at: datetime


@dataclass(frozen=True, slots=True)
class ClientAttention:
    """A client's rolled-up attention — the roster badge + the strip feed."""

    client_id: uuid.UUID
    needs_attention: bool
    attention_count: int
    items: list[AttentionItem]
    latest_at: datetime | None


def build_client_attention(client_id: uuid.UUID, items: Sequence[AttentionItem]) -> ClientAttention:
    """Pure rollup of one client's raw signals into its attention summary.

    The badge (``needs_attention`` / ``attention_count``) counts only the
    actionable, open-state kinds; ``items`` carries every signal newest-first so
    the strip shows recent activity too.
    """
    ordered = sorted(items, key=lambda i: i.at, reverse=True)
    actionable = [i for i in ordered if i.kind in _ACTIONABLE_KINDS]
    return ClientAttention(
        client_id=client_id,
        needs_attention=bool(actionable),
        attention_count=sum(i.count for i in actionable),
        items=ordered,
        latest_at=ordered[0].at if ordered else None,
    )


async def load_advisor_attention(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID | None = None,
) -> list[ClientAttention]:
    """Load + roll up every attention signal for an advisor's clients.

    Pass ``client_id`` to scope to one client (the client-detail strip); omit it
    for the whole roster (the Command Center overview). Returns one
    :class:`ClientAttention` per client that has *any* signal, newest-first;
    clients with nothing to show are simply absent (the roster reads absence as
    "no badge").
    """
    scope = [Client.owner_id == advisor_id]
    if client_id is not None:
        scope.append(Client.id == client_id)
    cutoff = datetime.now(UTC) - timedelta(days=RECENT_WINDOW_DAYS)

    # ── the itinerary spine: titles, client ownership, and the reconcile flag ──
    itinerary_rows = (
        await session.execute(
            select(
                Itinerary.id,
                Itinerary.client_id,
                Itinerary.title,
                Itinerary.reconcile_requested_at,
            )
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope)
        )
    ).all()
    title_by_itinerary: dict[uuid.UUID, str] = {}
    client_by_itinerary: dict[uuid.UUID, uuid.UUID] = {}
    by_client: dict[uuid.UUID, list[AttentionItem]] = {}
    for itin_id, cid, title, reconcile_at in itinerary_rows:
        title_by_itinerary[itin_id] = title
        client_by_itinerary[itin_id] = cid
        if reconcile_at is not None:
            by_client.setdefault(cid, []).append(
                AttentionItem(
                    kind="changes_requested",
                    itinerary_id=itin_id,
                    itinerary_title=title,
                    count=1,
                    at=reconcile_at,
                )
            )

    # ── unread human-thread messages for this advisor ─────────────────────────
    unread_rows = (
        await session.execute(
            select(
                Thread.client_id,
                Thread.itinerary_id,
                func.count(Message.id),
                func.max(Message.created_at),
            )
            .join(
                ThreadParticipant,
                and_(
                    ThreadParticipant.thread_id == Thread.id,
                    ThreadParticipant.actor_id == advisor_id,
                ),
            )
            .join(Client, Client.id == Thread.client_id)
            .join(
                Message,
                and_(
                    Message.thread_id == Thread.id,
                    Message.removed_at.is_(None),
                    Message.author_kind != ThreadActorKind.advisor,
                    or_(
                        ThreadParticipant.last_read_at.is_(None),
                        Message.created_at > ThreadParticipant.last_read_at,
                    ),
                ),
            )
            .where(Thread.archived_at.is_(None), *scope)
            .group_by(Thread.client_id, Thread.itinerary_id)
        )
    ).all()
    for cid, itin_id, count, latest_at in unread_rows:
        by_client.setdefault(cid, []).append(
            AttentionItem(
                kind="unread_messages",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id) if itin_id else None,
                count=int(count),
                at=latest_at,
            )
        )

    # ── recent traveler approvals (event-style, windowed) ─────────────────────
    approved_rows = (
        await session.execute(
            select(
                NodeHistory.itinerary_id,
                func.count(NodeHistory.id),
                func.max(NodeHistory.occurred_at),
            )
            .join(Itinerary, Itinerary.id == NodeHistory.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(
                *scope,
                NodeHistory.actor_kind == "traveler",
                NodeHistory.after["status"].astext == "approved",
                or_(
                    NodeHistory.before.is_(None),
                    NodeHistory.before["status"].astext != "approved",
                ),
                NodeHistory.occurred_at >= cutoff,
            )
            .group_by(NodeHistory.itinerary_id)
        )
    ).all()
    for itin_id, count, latest_at in approved_rows:
        cid = client_by_itinerary.get(itin_id)
        if cid is None:  # an approval on an itinerary outside this advisor's scope
            continue
        by_client.setdefault(cid, []).append(
            AttentionItem(
                kind="traveler_approved",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=int(count),
                at=latest_at,
            )
        )

    # ── recent succeeded payments (event-style, windowed) ─────────────────────
    payment_rows = (
        await session.execute(
            select(
                Invoice.itinerary_id,
                func.count(Payment.id),
                func.max(Payment.created_at),
            )
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(
                *scope,
                Payment.status == PaymentStatus.succeeded,
                Payment.created_at >= cutoff,
            )
            .group_by(Invoice.itinerary_id)
        )
    ).all()
    for itin_id, count, latest_at in payment_rows:
        cid = client_by_itinerary.get(itin_id)
        if cid is None:
            continue
        by_client.setdefault(cid, []).append(
            AttentionItem(
                kind="payment_received",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=int(count),
                at=latest_at,
            )
        )

    summaries = [build_client_attention(cid, items) for cid, items in by_client.items()]
    summaries.sort(key=lambda c: c.latest_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return summaries
