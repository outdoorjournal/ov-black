"""Advisor awareness feed — "what wants my attention", derived, no new table.

ADV-14 (Wave D), extended by Wave F (mission control). When an advisor returns
to the Command Center, nothing tells them *which* clients are waiting on them —
a change request lives inside one fork's Studio, approvals and payments require
walking into each trip. This service reads already-persisted signals and rolls
them up per client so the roster can badge the ones that need a hand, the
client page can show a "what's happened" strip, and the Ops dashboard can rank
a queue.

The signals split into two tiers:

- **Actionable (open-state)** — self-clear when the advisor does the work, so
  they drive the roster badge without ever going stale:
    - ``changes_requested`` — an open reconcile: the traveler asked staff to
      merge a fork's changes back (``itineraries.reconcile_requested_at``);
      cleared on merge/withdraw.
    - ``unread_messages`` — human-thread messages authored by someone other than
      the advisor, newer than the advisor's ``thread_participants.last_read_at``;
      cleared when the advisor opens the thread (:func:`messaging.list_messages`
      stamps the read watermark).
    - ``offer_expiring`` — a live (latest, un-superseded) priced offer on a
      not-yet-booked node lapses within :data:`OFFER_EXPIRY_HORIZON_HOURS`;
      cleared by re-pricing, booking, or the offer lapsing out of the window.
    - ``invoice_unpaid`` — an ``issued`` invoice (status is authoritative:
      settlement flips it to ``paid``); cleared on payment or void.
    - ``booking_unconfirmed`` — a booking with no supplier confirmation yet;
      cleared when the advisor records the confirmation # or cancels.
- **Recent activity (event-style, rolling window)** — informational context for
  the per-client strip only, *not* the badge (no persisted "last looked"
  watermark yet — see the plan's earns-it follow-up):
    - ``traveler_approved`` — the traveler approved cards in the last
      :data:`RECENT_WINDOW_DAYS` days (``node_history`` status → approved).
    - ``payment_received`` — a payment succeeded in the last window.
    - ``trip_proposed`` — the advisor proposed a plan in the last window; the
      ball is in the *traveler's* court, so it must never light the badge.

Each item carries ``urgency`` (open-state signals with a clock — an expiring
offer, an overdue invoice — rank above the rest) and ``deadline`` (the
countdown timestamp: offer ``expires_at``, invoice ``due_at``) so the Ops
queue can order by how overdue the advisor is, not just recency.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Booking,
    Client,
    Invoice,
    InvoiceStatus,
    Itinerary,
    ItineraryStatus,
    Message,
    Node,
    NodeHistory,
    NodeOffer,
    NodeStatus,
    Payment,
    PaymentStatus,
    Thread,
    ThreadActorKind,
    ThreadParticipant,
)

# Rolling window for the event-style (non-open-state) signals. Open-state
# signals (reconcile / unread / offer / invoice / booking) carry no window —
# they show while they're open.
RECENT_WINDOW_DAYS = 14

# How far ahead an offer's expiry counts as "expiring" (mission-control clock).
OFFER_EXPIRY_HORIZON_HOURS = 24

AttentionKind = Literal[
    "changes_requested",
    "unread_messages",
    "offer_expiring",
    "invoice_unpaid",
    "booking_unconfirmed",
    "traveler_approved",
    "payment_received",
    "trip_proposed",
]

Urgency = Literal["urgent", "normal"]

# The open-state signals — these and only these light the roster badge/dot,
# because
# they clear themselves when the advisor acts. Recent-activity signals are strip
# context, so a glanced-at client doesn't keep a stale count forever.
ACTIONABLE_KINDS: frozenset[str] = frozenset(
    {
        "changes_requested",
        "unread_messages",
        "offer_expiring",
        "invoice_unpaid",
        "booking_unconfirmed",
    }
)


def classify_urgency(
    kind: AttentionKind,
    *,
    deadline: datetime | None,
    now: datetime,
) -> Urgency:
    """Pure urgency rule: signals with a burning clock outrank the rest.

    An expiring offer is always urgent (it exists only inside its 24h horizon);
    an issued invoice turns urgent once past ``due_at``. Everything else is
    normal — including the recent-activity tier, which never carries urgency.
    """
    if kind == "offer_expiring":
        return "urgent"
    if kind == "invoice_unpaid" and deadline is not None and deadline < now:
        return "urgent"
    return "normal"


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One signal on one (client, itinerary) — a row in the per-client strip.

    ``itinerary_id`` is None for a basecamp-scoped thread's unread (a client-wide
    conversation not tied to a single trip); every other kind is trip-scoped.
    ``node_id`` is set on node-scoped signals (offer_expiring,
    booking_unconfirmed). ``deadline`` is the countdown timestamp where one
    exists (offer ``expires_at``, invoice ``due_at``); ``at`` stays "when this
    signal arose".
    """

    kind: AttentionKind
    itinerary_id: uuid.UUID | None
    itinerary_title: str | None
    count: int
    at: datetime
    node_id: uuid.UUID | None = None
    urgency: Urgency = "normal"
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClientAttention:
    """A client's rolled-up attention — the roster badge + the strip feed."""

    client_id: uuid.UUID
    full_name: str
    needs_attention: bool
    attention_count: int
    items: list[AttentionItem] = field(default_factory=list)
    latest_at: datetime | None = None


def build_client_attention(
    client_id: uuid.UUID,
    items: Sequence[AttentionItem],
    *,
    full_name: str = "",
) -> ClientAttention:
    """Pure rollup of one client's raw signals into its attention summary.

    The badge (``needs_attention`` / ``attention_count``) counts only the
    actionable, open-state kinds. ``items`` is queue-ordered — actionable
    before recent, urgent before normal, then newest-first — so the strip and
    the Ops queue read top-down; ``latest_at`` stays the true newest timestamp
    regardless of that ordering.
    """
    ordered = sorted(
        items,
        key=lambda i: (
            i.kind not in ACTIONABLE_KINDS,
            i.urgency != "urgent",
            -i.at.timestamp(),
        ),
    )
    actionable = [i for i in ordered if i.kind in ACTIONABLE_KINDS]
    return ClientAttention(
        client_id=client_id,
        full_name=full_name,
        needs_attention=bool(actionable),
        attention_count=sum(i.count for i in actionable),
        items=ordered,
        latest_at=max((i.at for i in items), default=None),
    )


async def load_advisor_attention(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[ClientAttention]:
    """Load + roll up every attention signal for an advisor's clients.

    Pass ``client_id`` to scope to one client (the client-detail strip); omit it
    for the whole roster (the Command Center overview). Returns one
    :class:`ClientAttention` per client that has *any* signal, newest-first;
    clients with nothing to show are simply absent (the roster reads absence as
    "no badge"). ``now`` is injectable for tests; defaults to the wall clock.
    """
    scope = [Client.owner_id == advisor_id]
    if client_id is not None:
        scope.append(Client.id == client_id)
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=RECENT_WINDOW_DAYS)
    offer_horizon = now + timedelta(hours=OFFER_EXPIRY_HORIZON_HOURS)

    # ── client names (the queue renders them without a roster join) ───────────
    name_rows = (await session.execute(select(Client.id, Client.full_name).where(*scope))).all()
    name_by_client: dict[uuid.UUID, str] = dict(name_rows)  # type: ignore[arg-type]

    # ── the itinerary spine: titles, ownership, reconcile + proposed flags ────
    itinerary_rows = (
        await session.execute(
            select(
                Itinerary.id,
                Itinerary.client_id,
                Itinerary.title,
                Itinerary.reconcile_requested_at,
                Itinerary.status,
                Itinerary.proposed_at,
            )
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope)
        )
    ).all()
    title_by_itinerary: dict[uuid.UUID, str] = {}
    client_by_itinerary: dict[uuid.UUID, uuid.UUID] = {}
    by_client: dict[uuid.UUID, list[AttentionItem]] = {}

    def _add(cid: uuid.UUID, item: AttentionItem) -> None:
        by_client.setdefault(cid, []).append(item)

    for itin_id, cid, title, reconcile_at, itin_status, proposed_at in itinerary_rows:
        title_by_itinerary[itin_id] = title
        client_by_itinerary[itin_id] = cid
        if reconcile_at is not None:
            _add(
                cid,
                AttentionItem(
                    kind="changes_requested",
                    itinerary_id=itin_id,
                    itinerary_title=title,
                    count=1,
                    at=reconcile_at,
                ),
            )
        if (
            itin_status is ItineraryStatus.proposed
            and proposed_at is not None
            and proposed_at >= cutoff
        ):
            _add(
                cid,
                AttentionItem(
                    kind="trip_proposed",
                    itinerary_id=itin_id,
                    itinerary_title=title,
                    count=1,
                    at=proposed_at,
                ),
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
        _add(
            cid,
            AttentionItem(
                kind="unread_messages",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id) if itin_id else None,
                count=int(count),
                at=latest_at,
            ),
        )

    # ── live offers lapsing inside the horizon (node-scoped, always urgent) ───
    superseded = (
        select(NodeOffer.refreshed_from_offer_id)
        .where(NodeOffer.refreshed_from_offer_id.is_not(None))
        .scalar_subquery()
    )
    offer_rows = (
        await session.execute(
            select(
                Node.itinerary_id,
                NodeOffer.node_id,
                NodeOffer.priced_at,
                NodeOffer.expires_at,
            )
            .join(Node, Node.id == NodeOffer.node_id)
            .join(Itinerary, Itinerary.id == Node.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(
                *scope,
                Node.deleted_at.is_(None),
                Node.is_selected_alt.is_(True),
                Node.status.notin_([NodeStatus.booked, NodeStatus.confirmed, NodeStatus.discarded]),
                NodeOffer.expires_at.is_not(None),
                NodeOffer.expires_at > now,
                NodeOffer.expires_at <= offer_horizon,
                NodeOffer.id.notin_(superseded),
            )
        )
    ).all()
    for itin_id, node_id, priced_at, expires_at in offer_rows:
        cid = client_by_itinerary.get(itin_id)
        if cid is None:
            continue
        _add(
            cid,
            AttentionItem(
                kind="offer_expiring",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=1,
                at=priced_at,
                node_id=node_id,
                urgency=classify_urgency("offer_expiring", deadline=expires_at, now=now),
                deadline=expires_at,
            ),
        )

    # ── issued invoices awaiting payment (status is authoritative) ────────────
    invoice_rows = (
        await session.execute(
            select(
                Invoice.itinerary_id,
                Invoice.issued_at,
                Invoice.updated_at,
                Invoice.due_at,
            )
            .join(Itinerary, Itinerary.id == Invoice.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(*scope, Invoice.status == InvoiceStatus.issued)
        )
    ).all()
    for itin_id, issued_at, updated_at, due_at in invoice_rows:
        cid = client_by_itinerary.get(itin_id)
        if cid is None:
            continue
        # Pre-0042 invoices were issued before issued_at existed — fall back.
        arose_at = issued_at or updated_at
        _add(
            cid,
            AttentionItem(
                kind="invoice_unpaid",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=1,
                at=arose_at,
                urgency=classify_urgency("invoice_unpaid", deadline=due_at, now=now),
                deadline=due_at,
            ),
        )

    # ── bookings awaiting a supplier confirmation # ───────────────────────────
    booking_rows = (
        await session.execute(
            select(Node.itinerary_id, Booking.node_id, Booking.booked_at)
            .join(Node, Node.id == Booking.node_id)
            .join(Itinerary, Itinerary.id == Node.itinerary_id)
            .join(Client, Client.id == Itinerary.client_id)
            .where(
                *scope,
                Booking.confirmed_at.is_(None),
                Booking.cancelled_at.is_(None),
            )
        )
    ).all()
    for itin_id, node_id, booked_at in booking_rows:
        cid = client_by_itinerary.get(itin_id)
        if cid is None:
            continue
        _add(
            cid,
            AttentionItem(
                kind="booking_unconfirmed",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=1,
                at=booked_at,
                node_id=node_id,
            ),
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
        _add(
            cid,
            AttentionItem(
                kind="traveler_approved",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=int(count),
                at=latest_at,
            ),
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
        _add(
            cid,
            AttentionItem(
                kind="payment_received",
                itinerary_id=itin_id,
                itinerary_title=title_by_itinerary.get(itin_id),
                count=int(count),
                at=latest_at,
            ),
        )

    summaries = [
        build_client_attention(cid, items, full_name=name_by_client.get(cid, ""))
        for cid, items in by_client.items()
    ]
    summaries.sort(key=lambda c: c.latest_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return summaries
