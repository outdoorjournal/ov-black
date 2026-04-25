"""Advisor-facing roster of itineraries — one row per draft/approved trip.

This is the plural-namespace counterpart to ``/itinerary/{id}`` (singular,
shared between advisor + traveler) and ``/me/itineraries`` (traveler's
own, lean shape). Returns a rich row that embeds the owning client so
the Command Center can render the entire roster in a dense table without
N+1 lookups.

Gated by :func:`require_advisor`. Scope is the calling advisor's clients
(``clients.owner_id = advisor_id``) — orphan itineraries with no client
(``itineraries.client_id IS NULL``) are intentionally excluded; the
advisor-facing view never wants those.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, Itinerary, ItineraryStatus
from app.routers.clients import _advisor_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.advisor_itineraries")

router = APIRouter(prefix="/itineraries", tags=["itineraries"])


class AdvisorItineraryClient(BaseModel):
    """Embedded client shape for the advisor roster row."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr


class AdvisorItinerarySummary(BaseModel):
    """Row shape for the advisor roster of itineraries."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    title: str
    status: ItineraryStatus
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    last_activity_at: datetime
    client: AdvisorItineraryClient
    needs_attention: Literal[False] = False


class AdvisorItinerariesResponse(BaseModel):
    """Envelope for ``GET /itineraries`` (advisor)."""

    model_config = ConfigDict(extra="forbid")

    itineraries: list[AdvisorItinerarySummary]


@router.get(
    "",
    response_model=AdvisorItinerariesResponse,
    summary="List every itinerary across the calling advisor's clients.",
)
async def list_advisor_itineraries_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> AdvisorItinerariesResponse:
    advisor_id = _advisor_id(user)

    stmt = (
        select(Itinerary, Client)
        .join(Client, Client.id == Itinerary.client_id)
        .where(Client.owner_id == advisor_id)
        .order_by(Itinerary.updated_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    return AdvisorItinerariesResponse(
        itineraries=[
            AdvisorItinerarySummary(
                id=itinerary.id,
                title=itinerary.title,
                status=itinerary.status or ItineraryStatus.draft,
                created_at=itinerary.created_at,
                updated_at=itinerary.updated_at,
                approved_at=itinerary.approved_at,
                last_activity_at=itinerary.updated_at,
                client=AdvisorItineraryClient(
                    id=client.id,
                    full_name=client.full_name,
                    email=client.email,
                ),
            )
            for itinerary, client in rows
        ]
    )
