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
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
    Itinerary,
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
