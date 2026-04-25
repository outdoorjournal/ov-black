"""Onboarding-flow read surface.

A single endpoint for v1: ``GET /onboarding/openers/random`` returns one
randomly-chosen prompt from the curated bank in ``onboarding_openers``.
The basecamp page server-side fetches this when a brand-new client lands
without any prior agent turns, then renders the prompt as the page's
single Cormorant heading and ships it to the agent as ``seeded_opener``
when the user submits their first reply.

Authenticated (``require_user``) — anon callers cannot enumerate the
bank. The table itself is service-role-only (matches every other table
in the repo, see ``0004_agent_sessions.sql:74-82``); routing through
FastAPI keeps the RLS posture uniform.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import OnboardingOpener

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardingOpenerResponse(BaseModel):
    """One randomly-chosen opening question for a brand-new client."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    prompt: str


@router.get(
    "/openers/random",
    response_model=OnboardingOpenerResponse,
    responses={
        404: {"description": "No enabled openers configured."},
    },
    summary="Pick one open-ended question to seed a new client's first turn.",
)
async def random_opener_endpoint(
    _user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> OnboardingOpenerResponse:
    row = (
        await session.execute(
            select(OnboardingOpener)
            .where(OnboardingOpener.enabled.is_(True))
            .order_by(func.random())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        # Empty bank is a deploy-time misconfiguration — surface it loudly
        # rather than silently returning an empty string the UI would have
        # to special-case.
        raise HTTPException(status_code=404, detail="no_openers_configured")
    return OnboardingOpenerResponse(id=row.id, prompt=row.prompt)
