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
from datetime import datetime, timezone

from sqlalchemy import func, select, text as sql_text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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


class InviteReissueOutcome(str, enum.Enum):
    """Terminal states of a re-issue attempt."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    ALREADY_REDEEMED = "already_redeemed"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class InviteReissueResult:
    outcome: InviteReissueOutcome
    issued: MagicLinkIssued | None = None


class InviteCancelOutcome(str, enum.Enum):
    """Terminal states of a cancel attempt."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    NO_ACTIVE_INVITE = "no_active_invite"


@dataclass(frozen=True, slots=True)
class InviteCancelResult:
    outcome: InviteCancelOutcome


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


async def resolve_client_for_auth_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str | None,
) -> Client | None:
    """Find the ``clients`` row that belongs to an authenticated Supabase user.

    Used by ``GET /me/client`` so the web ``/auth/callback`` route can discover
    where to send a freshly magic-linked invitee. RLS on ``public.clients`` only
    permits advisors to select rows they own — clients can't answer this
    question against Supabase directly, which is why it lives behind the
    service-role-backed API.

    Two lookups, in order:

    1. By ``auth_user_id`` — the fast path after the link has been established.
    2. By case-insensitive ``email`` match against a clients row whose
       ``auth_user_id`` is still NULL. When this path hits, the link is
       backfilled in the same transaction (mirroring
       ``_jit_backfill_client_auth_user_id`` in ``services.agent``) and a
       ``profiles`` row with role='client' is upserted so subsequent reads
       resolve via the fast path.

    Returns ``None`` when nothing matches — the caller collapses to a 404 per
    the D015 existence-hiding precedent.
    """
    row = (
        await session.execute(select(Client).where(Client.auth_user_id == user_id))
    ).scalar_one_or_none()
    if row is not None:
        return row

    if not email:
        return None

    row = (
        await session.execute(
            select(Client).where(
                Client.auth_user_id.is_(None),
                func.lower(Client.email) == email.strip().lower(),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    try:
        await session.execute(
            update(Client)
            .where(Client.id == row.id, Client.auth_user_id.is_(None))
            .values(auth_user_id=user_id)
        )
        await session.execute(
            sql_text(
                "INSERT INTO public.profiles (id, role) "
                "VALUES (:user_id, 'client') ON CONFLICT (id) DO NOTHING"
            ),
            {"user_id": str(user_id)},
        )
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        return None

    row.auth_user_id = user_id
    logger.info(
        "clients.resolve.backfilled",
        extra={"client_id": str(row.id), "user_id": str(user_id)},
    )
    return row


async def _load_client_owned_by(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
) -> Client | None:
    """Load a client scoped to ``advisor_id`` or return ``None``.

    Mirrors the GET /clients/{id} scoping — collapsed shape, no 403.
    """
    result = await session.execute(
        select(Client).where(
            Client.id == client_id,
            Client.owner_id == advisor_id,
        )
    )
    return result.scalar_one_or_none()


async def reissue_client_invite(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    settings: Settings | None = None,
) -> InviteReissueResult:
    """Rotate the active invite for a client and email a fresh link.

    Supersedes any currently-active row for this (email, advisor), inserts
    a new row with a fresh code, and calls Supabase to send a new invite
    email. If a prior invite was already consumed, refuses with
    ``ALREADY_REDEEMED`` — a redeemed client has an auth row and should
    hit the normal magic-link flow, not a second invite.

    Atomicity mirrors ``create_client_with_voodoo_doll``: an upstream
    failure rolls back the supersede + insert so the advisor can retry
    without double-superseding.
    """
    settings = settings or get_settings()

    client = await _load_client_owned_by(
        session, advisor_id=advisor_id, client_id=client_id
    )
    if client is None:
        return InviteReissueResult(InviteReissueOutcome.CLIENT_NOT_FOUND)

    consumed_exists = await session.execute(
        select(Invite.code)
        .where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
            Invite.consumed_at.is_not(None),
        )
        .limit(1)
    )
    if consumed_exists.scalar_one_or_none() is not None:
        logger.info(
            "clients.reissue.already_redeemed",
            extra={"client_id": str(client_id), "advisor_id": str(advisor_id)},
        )
        return InviteReissueResult(InviteReissueOutcome.ALREADY_REDEEMED)

    now = datetime.now(timezone.utc)
    # Supersede every currently-active row for this (email, advisor). In
    # practice there is at most one, but we stamp any strays defensively so
    # the re-issue produces a single live code.
    await session.execute(
        update(Invite)
        .where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
            Invite.consumed_at.is_(None),
            Invite.cancelled_at.is_(None),
            Invite.superseded_at.is_(None),
        )
        .values(superseded_at=now)
    )

    new_invite = Invite(
        code=_generate_invite_code(),
        role=UserRole.client,
        email=client.email,
        created_by=advisor_id,
    )
    session.add(new_invite)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        logger.warning(
            "clients.reissue.flush_conflict",
            extra={"client_id": str(client_id), "advisor_id": str(advisor_id)},
        )
        return InviteReissueResult(InviteReissueOutcome.UPSTREAM_UNAVAILABLE)

    redirect_to = f"{settings.web_origin.rstrip('/')}/auth/callback?next=/command-center"
    try:
        issued = await generate_invite_link(client.email, redirect_to)
    except SupabaseAdminError as exc:
        await session.rollback()
        logger.warning(
            "clients.reissue.admin_failure",
            extra={
                "client_id": str(client_id),
                "advisor_id": str(advisor_id),
                "reason": exc.reason,
                "status": exc.status_code,
            },
        )
        return InviteReissueResult(InviteReissueOutcome.UPSTREAM_UNAVAILABLE)

    await session.commit()
    logger.info(
        "clients.reissue.ok",
        extra={"client_id": str(client_id), "advisor_id": str(advisor_id)},
    )
    return InviteReissueResult(InviteReissueOutcome.OK, issued=issued)


async def cancel_client_invite(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
) -> InviteCancelResult:
    """Cancel any active invite(s) for a client. No upstream call.

    Returns ``NO_ACTIVE_INVITE`` when there's nothing to cancel — either
    the client has no unredeemed rows (already consumed) or the advisor
    has already cancelled/superseded the outstanding one. Reissue still
    works in that case by inserting a fresh row.
    """
    client = await _load_client_owned_by(
        session, advisor_id=advisor_id, client_id=client_id
    )
    if client is None:
        return InviteCancelResult(InviteCancelOutcome.CLIENT_NOT_FOUND)

    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Invite)
        .where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
            Invite.consumed_at.is_(None),
            Invite.cancelled_at.is_(None),
            Invite.superseded_at.is_(None),
        )
        .values(cancelled_at=now)
        .returning(Invite.code)
    )
    cancelled_codes = list(result.scalars())
    if not cancelled_codes:
        return InviteCancelResult(InviteCancelOutcome.NO_ACTIVE_INVITE)

    await session.commit()
    logger.info(
        "clients.cancel_invite.ok",
        extra={
            "client_id": str(client_id),
            "advisor_id": str(advisor_id),
            "cancelled_count": len(cancelled_codes),
        },
    )
    return InviteCancelResult(InviteCancelOutcome.OK)
