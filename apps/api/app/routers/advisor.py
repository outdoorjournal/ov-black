"""Advisor ops surface — ``/advisor/*`` (Wave F, mission control).

The Command Center's roster-wide reads, all :func:`require_advisor` and scoped
to ``clients.owner_id``:

- ``GET /advisor/overview`` — portfolio stats: clients by invite state, trips
  by lifecycle, per-currency money position, agent heartbeat. The Ops
  dashboard's glance band.
- ``GET /advisor/activity`` — the merged, keyset-paged event feed (graph
  mutations, agent turns, messages, payments, invoice/booking beats).
- ``GET /advisor/money`` — the cross-client invoice roster + currency band.
- ``GET /advisor/feed`` — the live SSE stream (poll-to-push over the same
  activity projection; see :mod:`app.services.feed` for the frame contract).

The per-client awareness rollup stays in :mod:`app.routers.awareness`; this
module is the cross-roster grain.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.config import get_settings
from app.db import get_session, get_sessionmaker
from app.models import InvoiceStatus
from app.routers.clients import _advisor_id
from app.services.activity import (
    ALL_KINDS,
    ActivityEvent,
    ActivityKind,
    load_advisor_activity,
    next_cursor_for,
)
from app.services.advisor_money import (
    MoneyRow,
    MoneySummaryRow,
    load_advisor_money,
    next_money_cursor,
)
from app.services.advisor_overview import Portfolio, load_advisor_overview
from app.services.feed import stream_advisor_feed
from app.services.pagination import clamp_limit, require_cursor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/advisor", tags=["advisor"])


class ClientCountsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    uninvited: int
    pending: int
    active: int


class ItineraryCountsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    in_studio: int
    with_traveler: int
    approved: int
    open_forks: int
    reconcile_requested: int


class BillingRowOut(BaseModel):
    """One currency's roster-wide money position."""

    model_config = ConfigDict(extra="forbid")

    currency: str
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal


class SessionStatsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: int
    turns_7d: int
    errored_turns_7d: int
    avg_latency_ms_7d: int | None


class AdvisorOverviewResponse(BaseModel):
    """Envelope for ``GET /advisor/overview`` — the Ops glance band."""

    model_config = ConfigDict(extra="forbid")

    clients: ClientCountsOut
    itineraries: ItineraryCountsOut
    billing: list[BillingRowOut]
    sessions: SessionStatsOut
    generated_at: datetime


def _overview_out(p: Portfolio) -> AdvisorOverviewResponse:
    return AdvisorOverviewResponse(
        clients=ClientCountsOut(
            total=p.clients.total,
            uninvited=p.clients.uninvited,
            pending=p.clients.pending,
            active=p.clients.active,
        ),
        itineraries=ItineraryCountsOut(
            total=p.itineraries.total,
            in_studio=p.itineraries.in_studio,
            with_traveler=p.itineraries.with_traveler,
            approved=p.itineraries.approved,
            open_forks=p.itineraries.open_forks,
            reconcile_requested=p.itineraries.reconcile_requested,
        ),
        billing=[
            BillingRowOut(
                currency=row.currency,
                invoiced=row.invoiced,
                paid=row.paid,
                outstanding=row.outstanding,
            )
            for row in p.billing
        ],
        sessions=SessionStatsOut(
            active=p.sessions.active,
            turns_7d=p.sessions.turns_7d,
            errored_turns_7d=p.sessions.errored_turns_7d,
            avg_latency_ms_7d=p.sessions.avg_latency_ms_7d,
        ),
        generated_at=p.generated_at,
    )


@router.get(
    "/overview",
    response_model=AdvisorOverviewResponse,
    summary="Roster-wide portfolio stats for the calling advisor.",
)
async def get_advisor_overview_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> AdvisorOverviewResponse:
    advisor_id = _advisor_id(user)
    portfolio = await load_advisor_overview(session, advisor_id=advisor_id)
    return _overview_out(portfolio)


# ── activity feed ─────────────────────────────────────────────────────────────


class ActivityEventOut(BaseModel):
    """One projected event — ids/kinds/titles/timestamps, never content."""

    model_config = ConfigDict(extra="forbid")

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


class ActivityResponse(BaseModel):
    """Envelope for ``GET /advisor/activity`` — newest-first, keyset-paged."""

    model_config = ConfigDict(extra="forbid")

    events: list[ActivityEventOut]
    next_cursor: str | None


def _event_out(e: ActivityEvent) -> ActivityEventOut:
    return ActivityEventOut(
        kind=e.kind,
        at=e.at,
        source_id=e.source_id,
        client_id=e.client_id,
        itinerary_id=e.itinerary_id,
        itinerary_title=e.itinerary_title,
        actor_kind=e.actor_kind,
        title=e.title,
        op=e.op,
        status_before=e.status_before,
        status_after=e.status_after,
        amount=e.amount,
        currency=e.currency,
        ref_id=e.ref_id,
    )


def _parse_kinds(kinds: str | None) -> frozenset[str] | None:
    """Comma-separated ``kinds=`` → validated set; unknown names are a 400."""
    if kinds is None:
        return None
    wanted = {k.strip() for k in kinds.split(",") if k.strip()}
    if not wanted:
        return None
    unknown = wanted - ALL_KINDS
    if unknown:
        raise HTTPException(status_code=400, detail="unknown_kind")
    return frozenset(wanted)


@router.get(
    "/activity",
    response_model=ActivityResponse,
    summary="Merged roster activity feed, newest-first.",
)
async def get_advisor_activity_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    cursor: str | None = None,
    client_id: uuid.UUID | None = None,
    itinerary_id: uuid.UUID | None = None,
    kinds: str | None = Query(default=None, description="Comma-separated event kinds."),
) -> ActivityResponse:
    advisor_id = _advisor_id(user)
    page_limit = clamp_limit(limit)
    events = await load_advisor_activity(
        session,
        advisor_id=advisor_id,
        limit=page_limit,
        cursor=require_cursor(cursor),
        client_id=client_id,
        itinerary_id=itinerary_id,
        kinds=_parse_kinds(kinds),
    )
    return ActivityResponse(
        events=[_event_out(e) for e in events],
        next_cursor=next_cursor_for(events, page_limit),
    )


# ── money roster ──────────────────────────────────────────────────────────────


class MoneyRowOut(BaseModel):
    """One invoice, roster-legible (client + trip identity attached)."""

    model_config = ConfigDict(extra="forbid")

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


class MoneySummaryRowOut(BaseModel):
    """One currency's whole-roster position (issued+paid only)."""

    model_config = ConfigDict(extra="forbid")

    currency: str
    invoiced: Decimal
    paid: Decimal
    outstanding: Decimal


class AdvisorMoneyResponse(BaseModel):
    """Envelope for ``GET /advisor/money``."""

    model_config = ConfigDict(extra="forbid")

    invoices: list[MoneyRowOut]
    summary: list[MoneySummaryRowOut]
    next_cursor: str | None


def _money_row_out(row: MoneyRow) -> MoneyRowOut:
    return MoneyRowOut(
        id=row.id,
        client_id=row.client_id,
        client_name=row.client_name,
        itinerary_id=row.itinerary_id,
        itinerary_title=row.itinerary_title,
        label=row.label,
        status=row.status,
        currency=row.currency,
        total=row.total,
        settled=row.settled,
        issued_at=row.issued_at,
        due_at=row.due_at,
        created_at=row.created_at,
    )


def _money_summary_out(row: MoneySummaryRow) -> MoneySummaryRowOut:
    return MoneySummaryRowOut(
        currency=row.currency,
        invoiced=row.invoiced,
        paid=row.paid,
        outstanding=row.outstanding,
    )


@router.get(
    "/money",
    response_model=AdvisorMoneyResponse,
    summary="Cross-client invoice roster + per-currency position band.",
)
async def get_advisor_money_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    cursor: str | None = None,
    status: InvoiceStatus | None = None,
    client_id: uuid.UUID | None = None,
) -> AdvisorMoneyResponse:
    advisor_id = _advisor_id(user)
    page_limit = clamp_limit(limit)
    rows, summary = await load_advisor_money(
        session,
        advisor_id=advisor_id,
        limit=page_limit,
        cursor=require_cursor(cursor),
        status=status,
        client_id=client_id,
    )
    return AdvisorMoneyResponse(
        invoices=[_money_row_out(r) for r in rows],
        summary=[_money_summary_out(s) for s in summary],
        next_cursor=next_money_cursor(rows, page_limit),
    )


# ── live feed (SSE) ───────────────────────────────────────────────────────────


@router.get(
    "/feed",
    summary="Live advisor activity stream (SSE, data-only JSON frames).",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "text/event-stream of hello / activity / heartbeat / bye "
                "frames — see app/services/feed.py for the v1 contract."
            ),
            "content": {"text/event-stream": {}},
        }
    },
)
async def advisor_feed_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    cursor: str | None = Query(
        default=None,
        description="ISO-8601 resume watermark (the last seen frame's cursor).",
    ),
) -> StreamingResponse:
    """Auth is validated once at open; the stream self-terminates at
    min(JWT exp, feed_max_stream_seconds) with a ``bye`` so a stale token
    can't hold a feed forever. Uses the sessionmaker (short session per tick),
    never the request-scoped ``get_session``."""
    advisor_id = _advisor_id(user)
    resume: datetime | None = None
    if cursor is not None:
        try:
            resume = datetime.fromisoformat(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_cursor") from None

    exp_claim = user.claims.get("exp")
    token_exp = (
        datetime.fromtimestamp(exp_claim, tz=UTC) if isinstance(exp_claim, int | float) else None
    )
    body = stream_advisor_feed(
        get_sessionmaker(),
        advisor_id=advisor_id,
        settings=get_settings(),
        cursor=resume,
        token_exp=token_exp,
    )
    return StreamingResponse(
        content=body,
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )
