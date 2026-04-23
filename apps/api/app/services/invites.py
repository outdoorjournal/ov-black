"""Invite-code redemption logic.

The single entry point — :func:`redeem_invite` — validates an invite code,
atomically marks it consumed, and asks Supabase Auth to email a magic link
to the intended recipient. Outcomes are enumerated so the HTTP layer can
map each to a specific status + reason without leaking DB internals.

Atomicity: consumption uses ``UPDATE ... WHERE consumed_at IS NULL
RETURNING`` so concurrent redemptions of the same code cannot both succeed
— the second one comes back with zero rows. The DB is the source of truth
for single-use, not application code.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invite
from app.services.supabase_admin import (
    MagicLinkIssued,
    SupabaseAdminError,
    generate_magic_link,
)

logger = logging.getLogger("ov_black.invites")


class RedeemOutcome(str, enum.Enum):
    """All terminal states of a redeem attempt."""

    OK = "ok"
    UNKNOWN_CODE = "unknown_code"
    ALREADY_CONSUMED = "already_consumed"
    WRONG_EMAIL = "wrong_email"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class RedeemResult:
    outcome: RedeemOutcome
    issued: MagicLinkIssued | None = None


def _emails_match(invite_email: str | None, provided: str) -> bool:
    """Invites may be open (email is NULL) or pinned to a single address.

    Pinned invites must match case-insensitively — users do not reliably
    type their own email the same way they gave it to the advisor.
    """
    if invite_email is None:
        return True
    return invite_email.strip().lower() == provided.strip().lower()


async def redeem_invite(
    session: AsyncSession,
    *,
    code: str,
    email: str,
) -> RedeemResult:
    """Validate + consume ``code`` and issue a magic link to ``email``.

    The session is committed on the successful path; on failure the caller
    gets a ``RedeemResult`` with the specific outcome and no DB mutation.
    """
    normalized_code = code.strip()
    if not normalized_code or not email.strip():
        return RedeemResult(RedeemOutcome.UNKNOWN_CODE)

    invite = (
        await session.execute(
            select(Invite).where(Invite.code == normalized_code)
        )
    ).scalar_one_or_none()

    if invite is None:
        logger.info("invite.redeem.unknown_code")
        return RedeemResult(RedeemOutcome.UNKNOWN_CODE)

    if invite.consumed_at is not None:
        logger.info("invite.redeem.already_consumed", extra={"code_hint": normalized_code[:4]})
        return RedeemResult(RedeemOutcome.ALREADY_CONSUMED)

    # Cancelled and superseded both mean "this specific code is no longer
    # live" — collapse them into UNKNOWN_CODE so the public response is
    # indistinguishable from an invented code. Advisors manage lifecycle;
    # redeemers should look at their latest email.
    if invite.cancelled_at is not None:
        logger.info("invite.redeem.cancelled", extra={"code_hint": normalized_code[:4]})
        return RedeemResult(RedeemOutcome.UNKNOWN_CODE)
    if invite.superseded_at is not None:
        logger.info("invite.redeem.superseded", extra={"code_hint": normalized_code[:4]})
        return RedeemResult(RedeemOutcome.UNKNOWN_CODE)

    if not _emails_match(invite.email, email):
        logger.info("invite.redeem.wrong_email", extra={"code_hint": normalized_code[:4]})
        return RedeemResult(RedeemOutcome.WRONG_EMAIL)

    now = datetime.now(timezone.utc)
    consumed = await session.execute(
        update(Invite)
        .where(
            Invite.code == normalized_code,
            Invite.consumed_at.is_(None),
            Invite.cancelled_at.is_(None),
            Invite.superseded_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(Invite.code)
    )
    if consumed.scalar_one_or_none() is None:
        # Lost the race against a concurrent redeem — treat as already-consumed.
        logger.info("invite.redeem.race_lost", extra={"code_hint": normalized_code[:4]})
        await session.rollback()
        return RedeemResult(RedeemOutcome.ALREADY_CONSUMED)

    try:
        issued = await generate_magic_link(email)
    except SupabaseAdminError as exc:
        # Roll back so the invite stays redeemable — we never want a user
        # locked out by an upstream hiccup.
        await session.rollback()
        logger.warning(
            "invite.redeem.upstream_error",
            extra={"reason": exc.reason, "status": exc.status_code},
        )
        return RedeemResult(RedeemOutcome.UPSTREAM_UNAVAILABLE)

    await session.commit()
    logger.info("invite.redeem.ok", extra={"code_hint": normalized_code[:4]})
    return RedeemResult(RedeemOutcome.OK, issued=issued)
