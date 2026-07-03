"""Per-user self-service surface.

``GET /me/client`` resolves the ``clients`` row that belongs to the calling
Supabase user, performing a JIT backfill of ``clients.auth_user_id`` when the
link is still missing. It exists so the web ``/auth/callback`` route can
discover where to redirect a freshly magic-linked invitee: RLS on
``public.clients`` only allows advisors to select rows they own, so clients
can't answer this question against Supabase directly.

``GET /me/itineraries`` gives the Bedrock AgentCore agent read access to
the calling client's own itineraries. The agent forwards the client's
Supabase JWT when it invokes tools, so the same routes serve both the
client's own browser and the agent acting on their behalf.

Dossier and OSINT are intentionally NOT exposed here — those are private
to the advisor and never readable by the traveler. The agent reads them
via ``GET /agent/context`` using a per-session agent token issued at
``POST /sessions``; that path bypasses Supabase JWT auth entirely.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import (
    AgentSession,
    AgentTurn,
    InvoiceStatus,
    Itinerary,
    ItineraryStatus,
    ProfileFact,
    SessionAudience,
    TurnRole,
)
from app.services import invoices as invoices_svc
from app.services.clients import resolve_client_for_auth_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.me")

router = APIRouter(prefix="/me", tags=["me"])


class MyClientResponse(BaseModel):
    """Response for ``GET /me/client`` — the client_id the caller belongs to."""

    client_id: uuid.UUID


class MyItinerarySummary(BaseModel):
    """Row shape for ``GET /me/itineraries``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: ItineraryStatus
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None


class MyItinerariesResponse(BaseModel):
    """Envelope for ``GET /me/itineraries``."""

    model_config = ConfigDict(from_attributes=True)

    itineraries: list[MyItinerarySummary]


class MyInvoiceSummary(BaseModel):
    """Row shape for ``GET /me/invoices`` — one invoice across any of the trips."""

    id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    total: Decimal
    due_at: datetime | None
    itinerary_id: uuid.UUID
    itinerary_title: str


class MyInvoicesResponse(BaseModel):
    """Envelope for ``GET /me/invoices``."""

    invoices: list[MyInvoiceSummary]


class MyOnboardingSessionResponse(BaseModel):
    """Summary of the calling client's most-recent ACTIVE agent session.

    ``session_id`` (and the dependent fields ``turn_count``,
    ``last_turn_at``, ``seeded_opener``) describe the current ongoing
    session — i.e. ``ended_at IS NULL``. ``has_prior_session`` is true
    iff the client has any session row at all, ended or not. Basecamp
    uses ``has_prior_session`` (rather than ``turn_count > 0``) to gate
    the first-prompt opener UI so a user who clicks Skip / Close is not
    re-shown the opener on the next page load.

    ``has_profile_facts`` is true iff the client has at least one
    non-redacted ``profile_facts`` row — i.e. the traveler has told us
    something about themselves. Basecamp combines it with the variant to
    decide the onboarding nudge: a client in the ``post_first_touch``
    state (a session exists, but no itinerary yet) with **no** profile
    facts skipped onboarding before we learned anything, so basecamp
    shows a gentle "finish your profile" reminder.

    All session-scoped fields are null when no active session exists.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID | None
    turn_count: int
    last_turn_at: datetime | None
    seeded_opener: str | None
    has_prior_session: bool
    has_profile_facts: bool


@router.get(
    "/client",
    response_model=MyClientResponse,
    responses={
        404: {"description": "No client row is linked to this user."},
    },
    summary="Resolve the client_id for the calling user (invitee chat entry).",
)
async def get_my_client_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyClientResponse:
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        logger.warning("me.client.malformed_sub", extra={"sub_hint": user.sub[:8]})
        raise HTTPException(status_code=404, detail="client_not_found") from None

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    return MyClientResponse(client_id=client.id)


@router.get(
    "/itineraries",
    response_model=MyItinerariesResponse,
    summary="List the calling client's itineraries — draft + approved.",
)
async def list_my_itineraries_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyItinerariesResponse:
    """Return the OFFICIAL itineraries (baselines) for the caller's client row.

    Needed for Q&A mode where the agent may need to enumerate the client's
    trips ("which trip is next?") before drilling into a specific graph.
    Forks (the traveler's private "My version" of a trip) are excluded — they
    are reached via the two-version toggle on the itinerary page, not listed as
    standalone trips. Orders newest-updated first. Empty list is a valid
    response — a client in onboarding has no itineraries yet.
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return MyItinerariesResponse(itineraries=[])

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return MyItinerariesResponse(itineraries=[])

    # Only OFFICIAL itineraries (baselines) list here. A fork is the traveler's
    # private "My version" of a trip — reached via the two-version toggle on the
    # itinerary page, never shown as a standalone trip card on basecamp.
    rows = (
        (
            await session.execute(
                select(Itinerary)
                .where(
                    Itinerary.client_id == client.id,
                    Itinerary.forked_from_id.is_(None),
                )
                .order_by(Itinerary.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return MyItinerariesResponse(
        itineraries=[MyItinerarySummary.model_validate(row) for row in rows]
    )


@router.get(
    "/invoices",
    response_model=MyInvoicesResponse,
    summary="List the calling client's invoices across all itineraries.",
)
async def list_my_invoices_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyInvoicesResponse:
    """Every invoice across the caller's trips, newest first.

    Owner-scoped via ``resolve_client_for_auth_user`` (the same self-scoping as
    ``/me/itineraries``), so a traveler only ever sees their own client's
    invoices. Empty list is valid. Each row links to the existing
    ``/invoices/{id}`` pay page.
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return MyInvoicesResponse(invoices=[])

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return MyInvoicesResponse(invoices=[])

    rows = await invoices_svc.list_invoices_for_client(session, client.id)
    return MyInvoicesResponse(
        invoices=[
            MyInvoiceSummary(
                id=view.invoice.id,
                label=view.invoice.label,
                status=view.invoice.status,
                currency=view.invoice.currency,
                total=view.total,
                due_at=view.invoice.due_at,
                itinerary_id=itin.id,
                itinerary_title=itin.title,
            )
            for view, itin in rows
        ]
    )


@router.get(
    "/onboarding_session",
    response_model=MyOnboardingSessionResponse,
    summary="Summarize the calling client's most-recent agent session.",
)
async def get_my_onboarding_session_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyOnboardingSessionResponse:
    """Return ``{session_id, turn_count, last_turn_at, seeded_opener}`` or all-null.

    Powers basecamp's "have we conversed yet?" decision: if ``turn_count``
    is zero we render the single-prompt opener UI; otherwise we render the
    persistent right-rail chat invite. Basecamp is a traveler-facing
    surface, so this is scoped to ``audience == traveler`` — an advisor
    session opened about this client (Command Center) must never leak into
    basecamp, or the traveler's chat would POST turns to a session the
    existence-hiding authz collapses to 404.
    """
    empty = MyOnboardingSessionResponse(
        session_id=None,
        turn_count=0,
        last_turn_at=None,
        seeded_opener=None,
        has_prior_session=False,
        has_profile_facts=False,
    )
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return empty

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return empty

    # Has any non-redacted profile fact been recorded for this client? Drives
    # the onboarding nudge — a post_first_touch client with none skipped before
    # telling us anything. Redacted (soft-deleted) facts don't count, matching
    # the active-fact filter used everywhere else (services/facts.py).
    has_profile_facts = bool(
        (
            await session.execute(
                select(func.count(ProfileFact.id)).where(
                    ProfileFact.client_id == client.id,
                    ProfileFact.redacted_at.is_(None),
                )
            )
        ).scalar_one()
    )

    # Has-prior is independent of active/ended status — it gates the
    # first-prompt opener UI so a Skip / Close click is not re-prompted
    # on the next basecamp visit.
    has_prior_session = bool(
        (
            await session.execute(
                select(func.count(AgentSession.id)).where(
                    AgentSession.client_id == client.id,
                    AgentSession.audience == SessionAudience.traveler,
                )
            )
        ).scalar_one()
    )

    agent_session = (
        await session.execute(
            select(AgentSession)
            .where(
                AgentSession.client_id == client.id,
                AgentSession.audience == SessionAudience.traveler,
                AgentSession.ended_at.is_(None),
            )
            .order_by(AgentSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if agent_session is None:
        return MyOnboardingSessionResponse(
            session_id=None,
            turn_count=0,
            last_turn_at=None,
            seeded_opener=None,
            has_prior_session=has_prior_session,
            has_profile_facts=has_profile_facts,
        )

    summary = (
        await session.execute(
            select(
                func.count(AgentTurn.id),
                func.max(AgentTurn.created_at),
            ).where(
                AgentTurn.session_id == agent_session.id,
                AgentTurn.role.in_((TurnRole.user, TurnRole.assistant)),
            )
        )
    ).one()
    turn_count = int(summary[0] or 0)
    last_turn_at = summary[1]

    return MyOnboardingSessionResponse(
        session_id=agent_session.id,
        turn_count=turn_count,
        last_turn_at=last_turn_at,
        seeded_opener=agent_session.seeded_opener,
        has_prior_session=has_prior_session,
        has_profile_facts=has_profile_facts,
    )
