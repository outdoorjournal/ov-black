"""Per-turn graph digest — the plan's live state, pre-rendered for the prompt.

AGT-2: the agent used to be blind to the itinerary's lifecycle and money state
unless it burned a ``get_itinerary`` call — and the tool never carried totals,
invoicing, or the trip's derived lifecycle position at all. This
module renders one compact plaintext block that
:func:`app.agent.traveler_context.assemble_traveler_context` appends to the
system prompt **every turn** (the prompt is rebuilt per turn, so the digest
never stacks — each turn sees exactly one, current snapshot). The same block is
mirrored as ``AgentContext.graph_digest`` for the ``get_traveler_context`` tool.

Contents: the trip's derived lifecycle bucket (with what the state *means*
for the publish flow — or the fork framing when pinned to a working copy),
node counts by status, per-currency trip totals, the uninvoiced remainder
(shared math with the advisor cockpit via
:mod:`app.services.billing_summary`), a pending reconcile request, and the
latest completed analysis' finding counts — the "material changes" the
opening-of-turn convention (AGT-4) asks the agent to surface.

Redaction: nothing here is Dossier/OSINT/net-worth — statuses, counts, and
money figures are all data the traveler can already see on their own surfaces.
Still, follow the house rule: never log the rendered text.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
    Itinerary,
    ItineraryTimingKind,
    Node,
    NodeStatus,
)
from app.services.billing_summary import BillingState, billing_state
from app.services.display_status import DisplayStatus, display_status_expr
from app.services.node_cost import resolve_party_size, sum_node_costs

_ZERO = Decimal("0.00")

# Lifecycle render order — pending first, firmest last, discarded never shown.
_STATUS_ORDER = (
    NodeStatus.pending,
    NodeStatus.approved,
    NodeStatus.booked,
    NodeStatus.confirmed,
)

_DISPLAY_STATUS_HINTS = {
    DisplayStatus.in_studio: (
        "in the studio — nothing is with the traveler yet on this official "
        "trip; content reaches it when a working version is published "
        "(reconciled) into it."
    ),
    DisplayStatus.with_traveler: (
        "with the traveler — published cards are pending their review; they "
        "approve card by card or all at once, and approval locks a card in."
    ),
    DisplayStatus.approved: (
        "approved — the traveler has approved the plan; next steps are money "
        "and booking, which staff execute."
    ),
}

_FORK_HINT = (
    "working version — a private copy of the official trip; edits here are "
    "proposals until staff publish (reconcile) them into the official version."
)


def render_graph_digest(
    *,
    display_status: DisplayStatus,
    is_fork: bool,
    status_counts: dict[NodeStatus, int],
    totals: dict[str, Decimal],
    party_size: int,
    billing: BillingState | None,
    reconcile_requested: bool,
    analysis_block_count: int | None,
    analysis_warn_count: int | None,
) -> str:
    """Pure renderer — the async loader gathers, this formats (unit-testable)."""
    lines: list[str] = []

    if is_fork:
        hint = _FORK_HINT
    else:
        hint = _DISPLAY_STATUS_HINTS.get(display_status, display_status.value)
    lines.append(f"Status: {hint}")

    total_cards = sum(status_counts.get(s, 0) for s in _STATUS_ORDER)
    if total_cards:
        parts = [f"{status_counts[s]} {s.value}" for s in _STATUS_ORDER if status_counts.get(s, 0)]
        locked = status_counts.get(NodeStatus.booked, 0) + status_counts.get(
            NodeStatus.confirmed, 0
        )
        suffix = " (booked/confirmed cards are locked)" if locked else ""
        lines.append(f"Cards: {total_cards} — {', '.join(parts)}{suffix}")
    else:
        lines.append("Cards: none yet")

    if totals:
        rendered = " + ".join(f"{amount} {ccy}" for ccy, amount in sorted(totals.items()))
        lines.append(f"Trip total: {rendered} (party of {party_size})")

    if billing is not None:
        for row in billing.rows:
            if row.invoiced > _ZERO:
                lines.append(
                    f"Invoiced: {row.invoiced} {row.currency} "
                    f"({row.paid} paid, {row.outstanding} outstanding)"
                )
            if row.uninvoiced > _ZERO:
                lines.append(
                    f"Uninvoiced: {row.uninvoiced} {row.currency} across "
                    f"{row.uninvoiced_count} approved card"
                    f"{'s' if row.uninvoiced_count != 1 else ''}"
                )

    if reconcile_requested:
        lines.append(
            "Pending: the traveler has asked staff to merge this alternative "
            "version into the agreed plan."
        )

    if analysis_block_count is not None or analysis_warn_count is not None:
        blocks = analysis_block_count or 0
        warns = analysis_warn_count or 0
        if blocks or warns:
            lines.append(
                f"Latest analysis: {blocks} blocking, {warns} warning "
                f"finding{'s' if (blocks + warns) != 1 else ''} — read them with "
                "``get_analysis_findings``."
            )

    return (
        "Live plan state (auto-refreshed every turn — trust it over conversation "
        "memory; call ``get_itinerary`` only when you need the cards themselves):\n"
        + "\n".join(f"- {line}" for line in lines)
    )


async def _latest_completed_analysis_counts(
    session: AsyncSession, itinerary_id: uuid.UUID
) -> tuple[int | None, int | None]:
    """(block, warn) finding counts of the latest completed run, or (None, None)."""
    analysis_id = (
        await session.execute(
            select(Analysis.id)
            .where(
                Analysis.itinerary_id == itinerary_id,
                Analysis.status == AnalysisStatus.completed,
            )
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if analysis_id is None:
        return (None, None)
    rows = (
        await session.execute(
            select(AnalysisFinding.severity, func.count(AnalysisFinding.id))
            .where(AnalysisFinding.analysis_id == analysis_id)
            .group_by(AnalysisFinding.severity)
        )
    ).all()
    by_severity = {severity: int(count) for severity, count in rows}
    return (
        by_severity.get(FindingSeverity.block, 0),
        by_severity.get(FindingSeverity.warn, 0),
    )


def _viewing_when(starts_at: object, *, pinned: bool, anchor: date | None) -> str | None:
    """Human day/time from a node's TSTZRANGE lower bound, or None.

    asyncpg hands back a ``Range`` with a ``.lower`` datetime. Honors the
    Day-N-until-pinned rule (Wave E): a card's absolute date is only a fact on a
    PINNED trip (exact dates the traveler chose). On an unpinned trip the stamped
    ``starts_at`` is a provisional layout coordinate — surfacing it as
    "2026-08-13" would feed the model a date the traveler never gave, so we
    render the honest "Day N · HH:MM" ordinal (from ``anchor``) instead, or omit
    the when entirely when nothing anchors even that.
    """
    lower = getattr(starts_at, "lower", None)
    if lower is None:
        return None
    try:
        clock = lower.strftime("%H:%M")
        if pinned:
            return str(lower.strftime("%Y-%m-%d %H:%M"))
        if anchor is not None:
            day_n = (lower.date() - anchor).days + 1
            if day_n >= 1:
                return f"Day {day_n} · {clock}"
        return None
    except (AttributeError, ValueError):
        return None


async def viewing_context_for_node(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID | None,
    node_id: str | None,
) -> str | None:
    """One-line ambient cue naming the card the user is looking at right now.

    Scoped hard to ``itinerary_id``: we only describe a node that belongs to
    this session's pinned itinerary (and isn't deleted), so a spoofed
    ``viewing_node_id`` can never surface a title from someone else's trip — the
    caller can already see every card on this itinerary. Returns None when
    there's nothing to say (no id, unpinned session, an unparseable/optimistic
    id, or the node doesn't match), in which case the prompt simply omits the
    cue — a bad hint never breaks the turn.
    """
    if itinerary_id is None or not node_id:
        return None
    try:
        parsed_id = uuid.UUID(node_id)
    except (ValueError, AttributeError):
        return None
    row = (
        await session.execute(
            select(
                Node.title,
                Node.type,
                Node.status,
                Node.starts_at,
                Node.cost_amount,
                Node.cost_currency,
            ).where(
                Node.id == parsed_id,
                Node.itinerary_id == itinerary_id,
                Node.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        return None
    title, node_type, status, starts_at, cost_amount, cost_currency = row

    # Resolve the trip's timing so the "when" honors the Day-N-until-pinned rule
    # (a card's calendar date is only real once the traveler pins exact dates).
    timing = (
        await session.execute(
            select(Itinerary.timing_kind, Itinerary.date_start, Itinerary.days_anchor).where(
                Itinerary.id == itinerary_id
            )
        )
    ).first()
    pinned = False
    anchor: date | None = None
    if timing is not None:
        timing_kind, date_start, days_anchor = timing
        pinned = timing_kind == ItineraryTimingKind.exact and date_start is not None
        # Day-1 anchor for the honest "Day N" ordinal on an unpinned trip.
        anchor = days_anchor or date_start

    cost = f"{cost_amount} {cost_currency}" if cost_amount is not None and cost_currency else None
    return render_viewing_context(
        title=title,
        node_type=node_type.value if hasattr(node_type, "value") else str(node_type),
        status=status.value if hasattr(status, "value") else str(status),
        when=_viewing_when(starts_at, pinned=pinned, anchor=anchor),
        cost=cost,
    )


def render_viewing_context(
    *,
    title: str | None,
    node_type: str,
    status: str,
    when: str | None,
    cost: str | None,
) -> str:
    """Pure renderer for the on-screen-focus cue (unit-testable; loader gathers).

    ``when``/``cost`` are folded in only when present, so a bare card degrades
    to just its type + status. The trailing instruction is what makes the cue
    *ambient*: resolve deictic references to this card, but don't announce it.
    """
    bits = [node_type, status]
    if when:
        bits.append(when)
    if cost:
        bits.append(cost)

    label = title.strip() if title and title.strip() else "an untitled card"
    return (
        f"On screen right now: the user is looking at '{label}' "
        f"({', '.join(bits)}) in this itinerary. Treat deictic references in "
        "their message ('this', 'it', 'that one', 'here') as this card unless "
        "they clearly mean something else. This is ambient awareness — don't "
        "announce that you can see their screen; just use it to stay on the same "
        "page."
    )


async def graph_digest_for_itinerary(
    session: AsyncSession, itinerary_id: uuid.UUID | None
) -> str | None:
    """Load + render the pinned itinerary's digest; None when unpinned."""
    if itinerary_id is None:
        return None
    itinerary_row = (
        await session.execute(
            select(
                Itinerary.forked_from_id,
                display_status_expr(),
                Itinerary.reconcile_requested_at,
            ).where(Itinerary.id == itinerary_id)
        )
    ).first()
    if itinerary_row is None:
        return None
    forked_from_id, display_status_value, reconcile_requested_at = itinerary_row

    count_rows = (
        await session.execute(
            select(Node.status, func.count(Node.id))
            .where(
                Node.itinerary_id == itinerary_id,
                Node.is_selected_alt.is_(True),
                Node.deleted_at.is_(None),
            )
            .group_by(Node.status)
        )
    ).all()
    status_counts = {status: int(count) for status, count in count_rows}

    totals = await sum_node_costs(session, itinerary_id)
    party_size = await resolve_party_size(session, itinerary_id)
    billing = await billing_state(session, itinerary_id)
    block_count, warn_count = await _latest_completed_analysis_counts(session, itinerary_id)

    return render_graph_digest(
        display_status=DisplayStatus(display_status_value),
        is_fork=forked_from_id is not None,
        status_counts=status_counts,
        totals=totals,
        party_size=party_size,
        billing=billing,
        reconcile_requested=reconcile_requested_at is not None,
        analysis_block_count=block_count,
        analysis_warn_count=warn_count,
    )
