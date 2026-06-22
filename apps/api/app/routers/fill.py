"""AI Fill HTTP surface (TravelGraph Phase 6 / B6).

One endpoint:

- ``POST /itinerary/{itinerary_id}/fill`` — rank feasible inventory candidates
  for a gap. **Read-only**: returning proposals mutates nothing.

Accepting a proposal is the existing
``POST /itinerary/{id}/nodes/from-inventory`` write — a ``FillProposal`` carries
the ``inventory_source``/``inventory_id`` that route consumes, so the proposed
node lands with full provenance through the normal ``add_node`` path. There is
deliberately no separate accept route (handoff §4 "when to write to the graph").

Sits behind the JWT middleware and reuses the itinerary draft-read gate
(``assert_itinerary_readable``) so Fill applies the exact same authorization as
reading the graph. Both the advisor and the owning client may call it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.inventory.registry import InventoryCtx
from app.models import Itinerary, NodeType
from app.routers.inventory import get_inventory_registry
from app.routers.itineraries import assert_itinerary_readable
from app.services.fill import FillProposal, GapWindow, fill_gap

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.inventory.registry import InventoryProviderRegistry
    from app.services.fill import FillResult

router = APIRouter(prefix="/itinerary", tags=["fill"])


# ── Request / response models ──────────────────────────────────────────────


class GapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class FillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap: GapModel
    party_id: uuid.UUID | None = None
    analysis_id: uuid.UUID | None = None
    desired_kinds: list[NodeType] | None = None
    min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    max_proposals: int = Field(default=8, ge=1, le=50)


class GeoPointResponse(BaseModel):
    lat: float
    lng: float


class FillProposalResponse(BaseModel):
    inventory_source: str
    inventory_id: str
    title: str
    type: NodeType
    starts_at: datetime
    ends_at: datetime
    location: GeoPointResponse | None
    score: float
    fits_in_gap: bool
    feasibility_unknown: bool
    drive_time_in_min: int | None
    drive_time_out_min: int | None
    party_ok: bool
    constraint_warnings: list[str]
    rationale: str


class FillResponse(BaseModel):
    proposals: list[FillProposalResponse]
    analysis_id: uuid.UUID | None
    analysis_age_seconds: int | None


def _proposal_response(p: FillProposal) -> FillProposalResponse:
    return FillProposalResponse(
        inventory_source=p.inventory_source,
        inventory_id=p.inventory_id,
        title=p.title,
        type=p.type,
        starts_at=p.starts_at,
        ends_at=p.ends_at,
        location=(
            GeoPointResponse(lat=p.location.lat, lng=p.location.lng)
            if p.location is not None
            else None
        ),
        score=p.score,
        fits_in_gap=p.fits_in_gap,
        feasibility_unknown=p.feasibility_unknown,
        drive_time_in_min=p.drive_time_in_min,
        drive_time_out_min=p.drive_time_out_min,
        party_ok=p.party_ok,
        constraint_warnings=p.constraint_warnings,
        rationale=p.rationale,
    )


def _fill_response(result: FillResult) -> FillResponse:
    return FillResponse(
        proposals=[_proposal_response(p) for p in result.proposals],
        analysis_id=result.analysis_id,
        analysis_age_seconds=result.analysis_age_seconds,
    )


@router.post(
    "/{itinerary_id}/fill",
    response_model=FillResponse,
    summary="Rank feasible inventory candidates for a gap (read-only).",
)
async def fill_gap_endpoint(
    itinerary_id: uuid.UUID,
    payload: FillRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> FillResponse:
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_readable(session, user, itinerary)

    result = await fill_gap(
        session,
        registry=registry,
        itinerary_id=itinerary_id,
        gap=GapWindow(start=payload.gap.start, end=payload.gap.end),
        party_id=payload.party_id,
        analysis_id=payload.analysis_id,
        desired_kinds=payload.desired_kinds,
        min_score=payload.min_score,
        max_proposals=payload.max_proposals,
        ctx=InventoryCtx(actor_kind="user", actor_id=user.sub),
    )
    return _fill_response(result)
