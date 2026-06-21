"""Role-based FastAPI dependencies layered on top of JWT validation.

The JWT middleware (``app.auth``) validates the token and attaches an
``AuthenticatedUser`` principal to the request. This module adds
application-role enforcement on top — specifically ``require_advisor``,
which looks up ``public.profiles`` by ``user.sub`` and 403s anyone whose
stored role is not ``UserRole.advisor``.

S03 scope: pure per-request DB lookup, no cache. The advisor surface is
a low-RPS internal tool; the S01 Known Limitations note flags a future
JWT custom-claim hook as the scalability path when the loop tightens.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import Profile, UserRole

logger = logging.getLogger("ov_black.auth_guards")


async def require_advisor(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    """Reject non-advisor principals with 403 ``advisor_only``.

    Looks up ``public.profiles`` by ``uuid.UUID(user.sub)``. Missing row
    or ``role != advisor`` both map to the same 403 — the reason string
    is logged (with an 8-char sub hint, never the full sub) but not
    returned to the caller.
    """
    sub_hint = user.sub[:8]

    try:
        sub_uuid = uuid.UUID(user.sub)
    except ValueError:
        logger.info(
            "auth_guards.require_advisor.reject",
            extra={"reason": "malformed_sub", "sub_hint": sub_hint},
        )
        raise HTTPException(status_code=403, detail="advisor_only") from None

    result = await session.execute(select(Profile).where(Profile.id == sub_uuid))
    profile = result.scalar_one_or_none()

    if profile is None:
        logger.info(
            "auth_guards.require_advisor.reject",
            extra={"reason": "profile_not_found", "sub_hint": sub_hint},
        )
        raise HTTPException(status_code=403, detail="advisor_only")

    if profile.role is not UserRole.advisor:
        logger.info(
            "auth_guards.require_advisor.reject",
            extra={"reason": "not_advisor", "sub_hint": sub_hint},
        )
        raise HTTPException(status_code=403, detail="advisor_only")

    return user
