"""Public auth surface — sign-in magic links.

One route mounted here, public (no JWT required — this is the front door
of the auth loop):

- ``POST /auth/login`` — email only; asks Supabase to email a magic
  link to an *existing* account. Unknown emails are collapsed into the
  same 204 response so the endpoint cannot be used to enumerate who
  has an account.

The route returns ``204 No Content`` on success — the link itself
never crosses this boundary. Clients get their account when an advisor
adds them (``POST /clients`` provisions the auth row + emails a welcome
link); after that they sign in here by email.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr

from app.services.login import LoginOutcome, request_login_link

logger = logging.getLogger("ov_black.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``."""

    email: EmailStr


async def rate_limit_login() -> None:
    """Rate-limit stub for sign-in requests.

    The dependency is wired from day one so enforcement can land later
    without touching the route.
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
