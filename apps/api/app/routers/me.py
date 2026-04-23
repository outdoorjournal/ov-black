"""Per-user self-service surface.

``GET /me/client`` resolves the ``clients`` row that belongs to the calling
Supabase user, performing a JIT backfill of ``clients.auth_user_id`` when the
link is still missing. It exists so the web ``/auth/callback`` route can
discover where to redirect a freshly magic-linked invitee: RLS on
``public.clients`` only allows advisors to select rows they own, so clients
can't answer this question against Supabase directly.

``GET /me/voodoo-doll`` and ``GET /me/itineraries`` give the Bedrock
AgentCore agent read access to the calling client's own data. The agent
forwards the client's Supabase JWT when it invokes tools, so the same
routes serve both the client's own browser and the agent acting on their
behalf — no advisor gate, no separate service-to-service credential.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import Itinerary, ItineraryStatus, VoodooDoll
from app.schemas.clients import VoodooDollDetail
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
    "/voodoo-doll",
    response_model=VoodooDollDetail,
    responses={
        404: {"description": "Caller has no client row, or no doll seeded yet."},
    },
    summary="Fetch the calling client's Voodoo Doll (agent read surface).",
)
async def get_my_voodoo_doll_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> VoodooDollDetail:
    """Return the caller's own Voodoo Doll.

    Mirrors the shape of ``ClientDetail.voodoo_doll`` returned by the
    advisor-facing ``GET /clients/{id}`` so the agent gets a stable, typed
    view it can render into its system prompt. Collapses client-not-found
    and doll-missing into a single 404 (D015 existence-hiding precedent).
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        raise HTTPException(status_code=404, detail="voodoo_doll_not_found") from None

    client = await resolve_client_for_auth_user(
        session, user_id=user_id, email=user.email
    )
    if client is None:
        raise HTTPException(status_code=404, detail="voodoo_doll_not_found")

    doll = (
        await session.execute(
            select(VoodooDoll).where(VoodooDoll.client_id == client.id)
        )
    ).scalar_one_or_none()
    if doll is None:
        raise HTTPException(status_code=404, detail="voodoo_doll_not_found")

    return VoodooDollDetail(
        id=doll.id,
        contact_preference=doll.contact_preference,
        group_type=doll.group_type,
        children_ages=list(doll.children_ages),
        travel_party_notes=doll.travel_party_notes,
        estimated_net_worth_usd=doll.estimated_net_worth_usd,
        passions=doll.passions,
        motivations=doll.motivations,
        travel_history=doll.travel_history,
        triggers=doll.triggers,
        constraints=doll.constraints,
        deal_breakers=doll.deal_breakers,
        dream_trip_signals=doll.dream_trip_signals,
        osint_notes=doll.osint_notes,
        created_at=doll.created_at,
        updated_at=doll.updated_at,
    )


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
