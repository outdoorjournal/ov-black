"""Demo / seed endpoints — TravelGraph Phase 4.

One advisor-only POST that materializes the Japan template into a
chosen client's account so the system can be shown off with a real
itinerary instead of just the prototype fixture. The endpoint:

1. Validates the target client exists and is owned by the calling
   advisor (so you can't seed an itinerary into someone else's book).
2. Find-or-creates the Japan template — idempotent across calls.
3. Instantiates the template at ``trip_start_at`` (defaults to
   30 days from now so it lands in the future).

Returns the new ``itinerary_id`` so the caller can deep-link straight
into Command Center.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client
from app.services.japan_template import build_japan_template
from app.services.templates import instantiate_template

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.demos")

router = APIRouter(prefix="/demos", tags=["demos"])


# Default trip start: 30 days from now, anchored at midnight UTC. Far
# enough out that demo itineraries don't overlap the advisor's actual
# calendar; midnight keeps offsets clean.
DEFAULT_TRIP_LEAD_DAYS = 30


class JapanInstantiateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    trip_start_at: datetime | None = Field(
        default=None,
        description=(
            "Trip start anchor. Defaults to 30 days from now at midnight UTC."
        ),
    )
    title: str | None = None


class JapanInstantiateResponse(BaseModel):
    itinerary_id: uuid.UUID
    template_slug: str
    template_version: int
    trip_start_at: datetime
    node_count: int
    edge_count: int


def _default_trip_start() -> datetime:
    now = datetime.now(timezone.utc)
    midnight = datetime(
        now.year, now.month, now.day, 0, 0, tzinfo=timezone.utc
    )
    return midnight + timedelta(days=DEFAULT_TRIP_LEAD_DAYS)


async def _resolve_client_owned_by(
    session: "AsyncSession",
    *,
    client_id: uuid.UUID,
    advisor_user_id: uuid.UUID,
) -> Client:
    client = (
        await session.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    if client.owner_id != advisor_user_id:
        raise HTTPException(status_code=403, detail="client_not_owned")
    return client


@router.post(
    "/japan",
    response_model=JapanInstantiateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Instantiate the Japan demo itinerary into an advisor's client.",
)
async def instantiate_japan_demo(
    payload: JapanInstantiateRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> JapanInstantiateResponse:
    """Create a fresh draft itinerary for ``client_id`` from the Japan
    template. The advisor must own the client; the response carries
    the new itinerary id.
    """
    try:
        advisor_uuid = uuid.UUID(user.sub)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=400, detail="invalid_user_sub"
        ) from exc

    client = await _resolve_client_owned_by(
        session, client_id=payload.client_id, advisor_user_id=advisor_uuid
    )

    template = await build_japan_template(session)
    trip_start_at = payload.trip_start_at or _default_trip_start()

    itinerary = await instantiate_template(
        session,
        template=template,
        client_id=client.id,
        trip_start_at=trip_start_at,
        title=payload.title or template.name,
        created_by=advisor_uuid,
    )

    # Re-count nodes / edges so the caller knows what landed.
    from app.models import Edge, Node  # local import to keep top-level light

    node_count = (
        await session.execute(
            select(Node.id).where(Node.itinerary_id == itinerary.id)
        )
    ).all()
    edge_count = (
        await session.execute(
            select(Edge.id).where(Edge.itinerary_id == itinerary.id)
        )
    ).all()

    logger.info(
        "demos.japan.instantiated",
        extra={
            "advisor_id": str(advisor_uuid),
            "client_id": str(client.id),
            "itinerary_id": str(itinerary.id),
            "template_id": str(template.id),
            "node_count": len(node_count),
            "edge_count": len(edge_count),
        },
    )
    return JapanInstantiateResponse(
        itinerary_id=itinerary.id,
        template_slug=template.slug,
        template_version=template.version,
        trip_start_at=trip_start_at,
        node_count=len(node_count),
        edge_count=len(edge_count),
    )
