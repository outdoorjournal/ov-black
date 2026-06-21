"""Public auth surface — invite redemption and sign-in magic links.

Two routes mounted here, both public (no JWT required — these are the
front doors of the auth loop):

- ``POST /auth/redeem-invite`` — invite code + email; consumes the
  invite and asks Supabase to email a first-time magic link.
- ``POST /auth/login`` — email only; asks Supabase to email a magic
  link to an *existing* account. Unknown emails are collapsed into the
  same 204 response so the endpoint cannot be used to enumerate who
  has an account.

Both routes return ``204 No Content`` on success — the link itself
never crosses this boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.db import get_session
from app.services.invites import RedeemOutcome, redeem_invite
from app.services.login import LoginOutcome, request_login_link

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
    session: AsyncSession = Depends(get_session),
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


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``."""

    email: EmailStr


async def rate_limit_login() -> None:
    """Rate-limit stub for sign-in requests.

    Mirror of ``rate_limit_redeem`` — the dependency is wired from day
    one so enforcement can land later without touching the route.
    """
    return None


@router.post(
    "/login",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {
            "description": (
                "Magic link sent, or silently treated as sent when no account "
                "matches the email (D015 enumeration guarantee)."
            )
        },
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Request a sign-in magic link for an existing account.",
)
async def login_endpoint(
    payload: LoginRequest,
    _rl: None = Depends(rate_limit_login),
) -> Response:
    result = await request_login_link(str(payload.email))

    if result.outcome in (LoginOutcome.OK, LoginOutcome.NO_ACCOUNT):
        # Collapse success and unknown-email into the same response so this
        # endpoint cannot be used to enumerate account existence.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if result.outcome is LoginOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    # Defensive — every enum value handled above.
    logger.error("login.unhandled_outcome", extra={"outcome": result.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")
