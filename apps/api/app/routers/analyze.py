"""Async Analyze HTTP surface (TravelGraph Phase 5 / B5).

Four endpoints under ``/itinerary/{itinerary_id}/analyses``:

- ``POST   /analyses``                 queue a run -> 202 {analysis_id, status}
- ``GET    /analyses?limit=``          list recent runs
- ``GET    /analyses/{analysis_id}``   one run + its findings
- ``POST   /analyses/{analysis_id}/cancel``  cancel a not-yet-terminal run

All sit behind the JWT middleware and reuse the itinerary draft-read gate
(``assert_itinerary_readable``) so reading/queueing an analysis applies the
exact same authorization as reading the graph. The runner itself executes in a
FastAPI ``BackgroundTask`` (handoff §3.4); the client polls the GET to observe
progress.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import (
    AnalysisDepth,
    AnalysisStatus,
    FindingSeverity,
    Itinerary,
)
from app.routers.itineraries import _actor_from_user, assert_itinerary_readable
from app.services.analyze import (
    cancel_analysis,
    create_queued_analysis,
    get_analysis,
    list_analyses,
    run_analysis,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/itinerary", tags=["analyze"])


# ── Request / response models ──────────────────────────────────────────────


class StartAnalysisRequest(BaseModel):
    depth: AnalysisDepth = AnalysisDepth.standard
    scope: dict[str, Any] = Field(default_factory=dict)
    force_rerun: bool = False


class AnalysisCreatedResponse(BaseModel):
    analysis_id: uuid.UUID
    status: AnalysisStatus
    cache_hit: bool = False
    in_flight: bool = False


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID | None
    severity: FindingSeverity
    category: str
    message: str
    evidence: dict[str, Any]
    suggested_fix: dict[str, Any] | None


class AnalysisSummaryResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    status: AnalysisStatus
    depth: AnalysisDepth
    summary: str | None
    error_detail: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AnalysisDetailResponse(AnalysisSummaryResponse):
    scope: dict[str, Any]
    result: dict[str, Any] | None
    external_calls: list[Any]
    findings: list[FindingResponse]


# ── helpers ─────────────────────────────────────────────────────────────────


async def _load_itinerary_for_read(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary_id: uuid.UUID,
) -> Itinerary:
    """Load the itinerary + apply the draft-read gate, or raise 404/403."""
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_readable(session, user, itinerary)
    return itinerary


def _summary_response(a: Any) -> AnalysisSummaryResponse:
    return AnalysisSummaryResponse(
        id=a.id,
        itinerary_id=a.itinerary_id,
        status=a.status,
        depth=a.depth,
        summary=a.summary,
        error_detail=a.error_detail,
        started_at=a.started_at,
        completed_at=a.completed_at,
        created_at=a.created_at,
    )


def _detail_response(a: Any, findings: list[Any]) -> AnalysisDetailResponse:
    return AnalysisDetailResponse(
        id=a.id,
        itinerary_id=a.itinerary_id,
        status=a.status,
        depth=a.depth,
        summary=a.summary,
        error_detail=a.error_detail,
        started_at=a.started_at,
        completed_at=a.completed_at,
        created_at=a.created_at,
        scope=a.scope or {},
        result=a.result,
        external_calls=a.external_calls or [],
        findings=[FindingResponse.model_validate(f) for f in findings],
    )


# ── endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "/{itinerary_id}/analyses",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalysisCreatedResponse,
    summary="Queue an Analyze run over an itinerary.",
)
async def start_analysis_endpoint(
    itinerary_id: uuid.UUID,
    payload: StartAnalysisRequest,
    background: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisCreatedResponse:
    await _load_itinerary_for_read(session, user, itinerary_id)
    actor = _actor_from_user(user)
    outcome = await create_queued_analysis(
        session,
        itinerary_id=itinerary_id,
        depth=payload.depth,
        scope=payload.scope,
        requested_by=actor.user_id,
        requested_kind="user",
        force_rerun=payload.force_rerun,
    )
    # Only a freshly-queued row is handed to the background runner; an
    # in-flight run or a cache hit returns its existing row untouched.
    if outcome.scheduled:
        background.add_task(run_analysis, outcome.analysis.id)
    return AnalysisCreatedResponse(
        analysis_id=outcome.analysis.id,
        status=outcome.analysis.status,
        cache_hit=outcome.cache_hit,
        in_flight=outcome.in_flight,
    )


@router.get(
    "/{itinerary_id}/analyses",
    response_model=list[AnalysisSummaryResponse],
    summary="List recent Analyze runs for an itinerary.",
)
async def list_analyses_endpoint(
    itinerary_id: uuid.UUID,
    limit: int = 20,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[AnalysisSummaryResponse]:
    await _load_itinerary_for_read(session, user, itinerary_id)
    rows = await list_analyses(session, itinerary_id=itinerary_id, limit=max(1, min(limit, 100)))
    return [_summary_response(a) for a in rows]


@router.get(
    "/{itinerary_id}/analyses/{analysis_id}",
    response_model=AnalysisDetailResponse,
    summary="Get one Analyze run and its findings.",
)
async def get_analysis_endpoint(
    itinerary_id: uuid.UUID,
    analysis_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetailResponse:
    await _load_itinerary_for_read(session, user, itinerary_id)
    found = await get_analysis(session, itinerary_id=itinerary_id, analysis_id=analysis_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not_found")
    analysis, findings = found
    return _detail_response(analysis, findings)


@router.post(
    "/{itinerary_id}/analyses/{analysis_id}/cancel",
    response_model=AnalysisDetailResponse,
    summary="Cancel a not-yet-terminal Analyze run (idempotent).",
)
async def cancel_analysis_endpoint(
    itinerary_id: uuid.UUID,
    analysis_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetailResponse:
    await _load_itinerary_for_read(session, user, itinerary_id)
    cancelled = await cancel_analysis(session, itinerary_id=itinerary_id, analysis_id=analysis_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="not_found")
    found = await get_analysis(session, itinerary_id=itinerary_id, analysis_id=analysis_id)
    assert found is not None  # just cancelled it
    analysis, findings = found
    return _detail_response(analysis, findings)
