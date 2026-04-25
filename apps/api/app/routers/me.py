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
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import AgentSession, AgentTurn, Itinerary, ItineraryStatus, TurnRole
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


class MyOnboardingSessionResponse(BaseModel):
    """Summary of the calling client's most-recent agent session.

    Returned shape is intentionally a "session metadata" object rather
    than a single ``has_prior`` boolean — basecamp derives whether to
    show the single-prompt opener UI from ``turn_count > 0``, and the
    same payload can later drive surfaces like "23 messages with your
    concierge" or "last spoke 4 days ago" without a new endpoint.

    All fields are null when the client has never opened a session
    (typical brand-new invitee landing on /basecamp for the first time).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID | None
    turn_count: int
    last_turn_at: datetime | None
    seeded_opener: str | None


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
    session: "AsyncSession" = Depends(get_session),
) -> MyClientResponse:
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        logger.warning("me.client.malformed_sub", extra={"sub_hint": user.sub[:8]})
        raise HTTPException(status_code=404, detail="client_not_found") from None

    client = await resolve_client_for_auth_user(
        session, user_id=user_id, email=user.email
    )
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
    session: "AsyncSession" = Depends(get_session),
) -> MyItinerariesResponse:
    """Return every itinerary that belongs to the caller's client row.

    Needed for Q&A mode where the agent may need to enumerate the client's
    trips ("which trip is next?") before drilling into a specific graph.
    Orders newest-updated first. Empty list is a valid response — a client
    in onboarding has no itineraries yet.
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return MyItinerariesResponse(itineraries=[])

    client = await resolve_client_for_auth_user(
        session, user_id=user_id, email=user.email
    )
    if client is None:
        return MyItinerariesResponse(itineraries=[])

    rows = (
        await session.execute(
            select(Itinerary)
            .where(Itinerary.client_id == client.id)
            .order_by(Itinerary.updated_at.desc())
        )
    ).scalars().all()
    return MyItinerariesResponse(
        itineraries=[MyItinerarySummary.model_validate(row) for row in rows]
    )


@router.get(
    "/onboarding_session",
    response_model=MyOnboardingSessionResponse,
    summary="Summarize the calling client's most-recent agent session.",
)
async def get_my_onboarding_session_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> MyOnboardingSessionResponse:
    """Return ``{session_id, turn_count, last_turn_at, seeded_opener}`` or all-null.

    Powers basecamp's "have we conversed yet?" decision: if ``turn_count``
    is zero we render the single-prompt opener UI; otherwise we render the
    persistent right-rail chat invite. Returns the most-recent session
    across all modes — the basecamp UI only branches on whether ANY
    conversation has happened, not on which mode it was in.
    """
    empty = MyOnboardingSessionResponse(
        session_id=None,
        turn_count=0,
        last_turn_at=None,
        seeded_opener=None,
    )
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return empty

    client = await resolve_client_for_auth_user(
        session, user_id=user_id, email=user.email
    )
    if client is None:
        return empty

    agent_session = (
        await session.execute(
            select(AgentSession)
            .where(AgentSession.client_id == client.id)
            .order_by(AgentSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if agent_session is None:
        return empty

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
    )
