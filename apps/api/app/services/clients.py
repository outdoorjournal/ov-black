"""Client creation service — atomic clients + voodoo_doll + invite write.

The single entry point :func:`create_client_with_voodoo_doll` wraps four
operations in one transaction (mirroring the S01 ``invites.py`` pattern):

1. INSERT ``clients`` (owner_id = advisor_id).
2. INSERT ``voodoo_dolls`` (client_id = above, authored_by = advisor_id).
3. INSERT ``invites`` (code, role=client, email, created_by=advisor_id).
4. Call Supabase ``generate_invite_link`` for the client email.

Atomicity is non-negotiable. If the upstream invite-link call fails the
whole transaction rolls back — there must never be a ``clients`` row
without a companion email going out. If the client email is already
tied to an existing client owned by the same advisor (case-insensitive
via the ``(owner_id, lower(email))`` unique index), the insert returns
``DUPLICATE_EMAIL`` without touching the invite table.

Logging is redaction-safe per the slice plan: we log the client email
(S01 precedent) and the new ``client_id`` UUID, but never the Supabase
service-role key, the Authorization header, the ``estimated_net_worth_usd``,
or the raw ``osint_notes``/``travel_history`` payloads.
"""

from __future__ import annotations

import enum
import logging
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Client, Invite, UserRole, VoodooDoll
from app.schemas.clients import ClientCreatePayload
from app.services.supabase_admin import (
    MagicLinkIssued,
    SupabaseAdminError,
    generate_invite_link,
)

logger = logging.getLogger("ov_black.clients")


class ClientCreateOutcome(str, enum.Enum):
    """Terminal states of a client-creation attempt."""

    OK = "ok"
    DUPLICATE_EMAIL = "duplicate_email"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class ClientCreateResult:
    outcome: ClientCreateOutcome
    client_id: uuid.UUID | None = None
    issued: MagicLinkIssued | None = None


def _generate_invite_code() -> str:
    """16 random bytes → ~22-char URL-safe string. Matches S01 convention."""
    return secrets.token_urlsafe(16)


async def create_client_with_voodoo_doll(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    payload: ClientCreatePayload,
    settings: Settings | None = None,
) -> ClientCreateResult:
    """Create a client + Voodoo Doll + invite and email the client a login link.

    All four operations share one transaction. On ``IntegrityError`` against
    ``clients_owner_email_idx`` we rollback and return ``DUPLICATE_EMAIL``;
    on ``SupabaseAdminError`` we rollback and return ``UPSTREAM_UNAVAILABLE``
    — the caller can surface those as 409 / 502 respectively. ``OK`` is only
    returned after a successful ``commit()``.
    """
    settings = settings or get_settings()
    email = str(payload.email)

    client = Client(
        owner_id=advisor_id,
        full_name=payload.full_name,
        email=email,
    )
    session.add(client)

    try:
        # Flush so the DB assigns client.id and we can catch the unique-index
        # violation synchronously — otherwise it would blow up on commit,
        # after we've already called Supabase.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        logger.info(
            "clients.create.duplicate_email",
            extra={"email": email, "advisor_id": str(advisor_id)},
        )
        return ClientCreateResult(ClientCreateOutcome.DUPLICATE_EMAIL)

    typed = payload.voodoo_doll.typed
    jsonb = payload.voodoo_doll.jsonb
    doll = VoodooDoll(
        client_id=client.id,
        authored_by=advisor_id,
        contact_preference=typed.contact_preference,
        group_type=typed.group_type,
        children_ages=list(typed.children_ages),
        travel_party_notes=typed.travel_party_notes,
        estimated_net_worth_usd=typed.estimated_net_worth_usd,
        passions=jsonb.passions,
        motivations=jsonb.motivations,
        travel_history=jsonb.travel_history,
        triggers=jsonb.triggers,
        constraints=jsonb.constraints,
        deal_breakers=jsonb.deal_breakers,
        dream_trip_signals=jsonb.dream_trip_signals,
        osint_notes=jsonb.osint_notes,
    )
    session.add(doll)

    invite = Invite(
        code=_generate_invite_code(),
        role=UserRole.client,
        email=email,
        created_by=advisor_id,
    )
    session.add(invite)

    try:
        await session.flush()
    except IntegrityError:
        # Extremely unlikely (token_urlsafe collision) but we still need to
        # roll back before calling Supabase.
        await session.rollback()
        logger.warning(
            "clients.create.invite_flush_conflict",
            extra={"email": email, "advisor_id": str(advisor_id)},
        )
        return ClientCreateResult(ClientCreateOutcome.DUPLICATE_EMAIL)

    redirect_to = f"{settings.web_origin.rstrip('/')}/auth/callback?next=/command-center"
    try:
        issued = await generate_invite_link(email, redirect_to)
    except SupabaseAdminError as exc:
        await session.rollback()
        logger.warning(
            "clients.create.admin_failure",
            extra={
                "email": email,
                "advisor_id": str(advisor_id),
                "reason": exc.reason,
                "status": exc.status_code,
            },
        )
        return ClientCreateResult(ClientCreateOutcome.UPSTREAM_UNAVAILABLE)

    await session.commit()
    logger.info(
        "clients.create.ok",
        extra={
            "email": email,
            "advisor_id": str(advisor_id),
            "client_id": str(client.id),
        },
    )
    return ClientCreateResult(
        ClientCreateOutcome.OK,
        client_id=client.id,
        issued=issued,
    )
