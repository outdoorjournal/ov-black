"""Public auth surface — invite redemption and magic-link issuance.

The one route mounted here, ``POST /auth/redeem-invite``, closes the S01
auth loop: advisor hands out an invite code, user submits it with their
email, the endpoint consumes the invite and asks Supabase to email a
magic link. We intentionally return ``204 No Content`` on success — the
link itself never crosses this boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.db import get_session
from app.services.invites import RedeemOutcome, redeem_invite

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


class RedeemInviteRequest(BaseModel):
    """Payload for ``POST /auth/redeem-invite``.

    Both fields are required; whitespace is trimmed at the service layer.
    """

    code: str = Field(min_length=1, max_length=128)
    email: EmailStr


async def rate_limit_redeem() -> None:
    """Rate-limit stub for invite redemption.

    Real enforcement (Redis/DynamoDB-backed counter keyed on IP + email)
    arrives in a later slice — the dependency is wired in day one so
    adding enforcement later does not require touching the route.
    """
    return None


@router.post(
    "/redeem-invite",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Magic link sent (or treated as sent)."},
        404: {"description": "Invite code is not redeemable for this email."},
        409: {"description": "Invite has already been consumed."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Redeem an invite code and request a magic-link email.",
)
async def redeem_invite_endpoint(
    payload: RedeemInviteRequest,
    session: "AsyncSession" = Depends(get_session),
    _rl: None = Depends(rate_limit_redeem),
) -> Response:
    result = await redeem_invite(
        session,
        code=payload.code,
        email=str(payload.email),
    )

    if result.outcome is RedeemOutcome.OK:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if result.outcome in (RedeemOutcome.UNKNOWN_CODE, RedeemOutcome.WRONG_EMAIL):
        # Collapse unknown-code and wrong-email into the same response so
        # attackers cannot enumerate valid codes by watching error shape.
        raise HTTPException(status_code=404, detail="invite_not_redeemable")
    if result.outcome is RedeemOutcome.ALREADY_CONSUMED:
        raise HTTPException(status_code=409, detail="invite_already_consumed")
    if result.outcome is RedeemOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    # Defensive — every enum value is handled above.
    logger.error("invite.redeem.unhandled_outcome", extra={"outcome": result.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")
