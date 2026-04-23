"""Per-user self-service surface.

``GET /me/client`` resolves the ``clients`` row that belongs to the calling
Supabase user, performing a JIT backfill of ``clients.auth_user_id`` when the
link is still missing. It exists so the web ``/auth/callback`` route can
discover where to redirect a freshly magic-linked invitee: RLS on
``public.clients`` only allows advisors to select rows they own, so clients
can't answer this question against Supabase directly.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.services.clients import resolve_client_for_auth_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.me")

router = APIRouter(prefix="/me", tags=["me"])


class MyClientResponse(BaseModel):
    """Response for ``GET /me/client`` — the client_id the caller belongs to."""

    client_id: uuid.UUID


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
