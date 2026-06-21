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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth import AuthenticatedUser, require_user
from app.db import get_session, get_sessionmaker
from app.models import OnboardingOpener
from app.services.agent import ActorContext, SessionOutcome, dismiss_onboarding
from app.services.clients import resolve_client_for_auth_user

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
    session: AsyncSession = Depends(get_session),
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


@router.post(
    "/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Onboarding dismissed (idempotent)."},
        404: {"description": "No client row is linked to this user."},
    },
    summary="Close any active onboarding/agent session for the calling client.",
)
async def dismiss_onboarding_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """End any active session and ensure ``has_prior_session`` is true.

    Used by basecamp's "Skip" (variant a) and "Close" (variant b)
    affordances. Idempotent — clicking twice is harmless. Collapses
    to 404 (D015) when the caller has no client row, so the route
    cannot be used to probe existence.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except ValueError:
        raise HTTPException(status_code=404, detail="client_not_found") from None

    client = await resolve_client_for_auth_user(session, user_id=user_uuid, email=user.email)
    if client is None:
        raise HTTPException(status_code=404, detail="client_not_found")

    actor = ActorContext(user_id=user_uuid, actor_kind="user", actor_id=user.sub)
    outcome = await dismiss_onboarding(
        get_sessionmaker(),
        actor=actor,
        client_id=client.id,
    )
    if outcome is not SessionOutcome.OK:
        raise HTTPException(status_code=404, detail="client_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
