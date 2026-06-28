"""Existing-user sign-in: email → Supabase magic link.

The auth row is provisioned when an advisor adds the client (``POST
/clients`` → ``generate_invite_link`` with ``create_user``). The sign-in
path here assumes the auth row already exists and refuses to create one
(``create_user=False``) — a stranger must be added by an advisor first,
not guess the sign-in form into provisioning themselves.

D015 enumeration guarantee applies: the public endpoint collapses
"unknown email" and "link sent" into the same 204 response so an
attacker cannot probe which emails have accounts. The classification
lives here so the router stays a thin translation layer.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from app.services.supabase_admin import (
    SupabaseAdminError,
    generate_magic_link,
)

logger = logging.getLogger("ov_black.login")


class LoginOutcome(str, enum.Enum):
    """Public outcomes of a sign-in request.

    ``OK`` and ``NO_ACCOUNT`` both map to HTTP 204 at the router — the
    distinction is kept here only for logging and tests.
    """

    OK = "ok"
    NO_ACCOUNT = "no_account"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class LoginResult:
    outcome: LoginOutcome


async def request_login_link(email: str) -> LoginResult:
    """Ask Supabase to email a magic link to ``email`` if an account exists.

    Calls ``generate_magic_link(email, create_user=False)``. If GoTrue
    rejects with a 4xx (typically 400/422 when the user is unknown and
    signups are disabled for OTP), we collapse to ``NO_ACCOUNT`` — the
    router still returns 204 so the response is indistinguishable from
    the success path. True network / 5xx failures surface as
    ``UPSTREAM_UNAVAILABLE`` so the user can retry instead of silently
    failing.
    """
    normalized = email.strip()
    if not normalized:
        return LoginResult(LoginOutcome.NO_ACCOUNT)

    try:
        await generate_magic_link(normalized, create_user=False)
    except SupabaseAdminError as exc:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            logger.info("login.no_account", extra={"status": exc.status_code})
            return LoginResult(LoginOutcome.NO_ACCOUNT)
        logger.warning(
            "login.upstream_error",
            extra={"reason": exc.reason, "status": exc.status_code},
        )
        return LoginResult(LoginOutcome.UPSTREAM_UNAVAILABLE)

    logger.info("login.link_issued")
    return LoginResult(LoginOutcome.OK)
