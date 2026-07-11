"""Client creation service — atomic clients + dossier + facts write.

The single entry point :func:`create_client_with_dossier` wraps the
following operations in one transaction:

1. INSERT ``clients`` (owner_id = advisor_id).
2. INSERT ``dossiers`` (client_id = above, authored_by = advisor_id) — the
   typed core only.
3. INSERT 0..N ``dossier_facts`` rows from ``payload.dossier_facts``
   (passions, motivations, …) so the existing onboarding form keeps its
   long-tail UX in a single round-trip.
4. Call Supabase ``generate_invite_link`` for the client email — this
   provisions the client's auth row and emails them a welcome sign-in
   link (no invite code; after this they sign in by email at ``/auth/login``).

Atomicity is non-negotiable. If the upstream invite-link call fails the
whole transaction rolls back — there must never be a ``clients`` row
without a companion welcome email going out. If the client email is
already tied to an existing client owned by the same advisor
(case-insensitive via the ``(owner_id, lower(email))`` unique index), the
insert returns ``DUPLICATE_EMAIL``.

Logging is redaction-safe: we log the client email and the new
``client_id`` UUID, but never the Supabase service-role key, the
Authorization header, the ``estimated_net_worth_usd``, or the raw fact
payloads.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import (
    Client,
    ClientContact,
    Dossier,
    DossierFact,
    OsintFact,
    ProfileFact,
)
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


class ResendWelcomeOutcome(str, enum.Enum):
    """Terminal states of a resend-welcome attempt."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    ALREADY_ACCEPTED = "already_accepted"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class ResendWelcomeResult:
    outcome: ResendWelcomeOutcome
    issued: MagicLinkIssued | None = None


async def create_client_with_dossier(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    payload: ClientCreatePayload,
    settings: Settings | None = None,
) -> ClientCreateResult:
    """Create a client + Dossier (+ optional initial dossier_facts) + invite.

    All operations share one transaction. On ``IntegrityError`` against
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
        address=payload.address,
        favorite_airport=(payload.favorite_airport.upper() if payload.favorite_airport else None),
        preferred_currency=(
            payload.preferred_currency.upper() if payload.preferred_currency else None
        ),
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

    typed = payload.dossier.typed
    dossier = Dossier(
        client_id=client.id,
        authored_by=advisor_id,
        contact_preference=typed.contact_preference,
        children_ages=list(typed.children_ages),
        travel_party_notes=typed.travel_party_notes,
        estimated_net_worth_usd=typed.estimated_net_worth_usd,
    )
    session.add(dossier)

    now = datetime.now(UTC)
    for fact_payload in payload.dossier_facts:
        session.add(
            DossierFact(
                client_id=client.id,
                kind=fact_payload.kind,
                text=fact_payload.text,
                source_kind=fact_payload.source_kind,
                source_ref=fact_payload.source_ref,
                observed_at=fact_payload.observed_at or now,
                recorded_by=advisor_id,
            )
        )
    for profile_payload in payload.profile_facts:
        session.add(
            ProfileFact(
                client_id=client.id,
                kind=profile_payload.kind,
                text=profile_payload.text,
                source_kind=profile_payload.source_kind,
                source_ref=profile_payload.source_ref,
                observed_at=profile_payload.observed_at or now,
                recorded_by=advisor_id,
            )
        )
    for osint_payload in payload.osint_facts:
        session.add(
            OsintFact(
                client_id=client.id,
                kind=osint_payload.kind,
                text=osint_payload.text,
                source_kind=osint_payload.source_kind,
                source_ref=osint_payload.source_ref,
                observed_at=osint_payload.observed_at or now,
                recorded_by=advisor_id,
            )
        )
    for contact_payload in payload.contacts:
        session.add(
            ClientContact(
                client_id=client.id,
                kind=contact_payload.kind,
                value=contact_payload.value,
                label=contact_payload.label,
            )
        )

    if not payload.notify:
        # Silent create (ADV-1 / invite-later): persist the client + Dossier
        # but mint NO auth row and send NO welcome email. ``invited_at`` stays
        # NULL, so the client reads as ``uninvited`` until the advisor invites
        # them later via ``resend_welcome_email`` (which stamps it then).
        await session.commit()
        logger.info(
            "clients.create.ok_silent",
            extra={
                "email": email,
                "advisor_id": str(advisor_id),
                "client_id": str(client.id),
            },
        )
        return ClientCreateResult(ClientCreateOutcome.OK, client_id=client.id)

    redirect_to = f"{settings.web_origin.rstrip('/')}/auth/callback?next=/basecamp"
    try:
        issued = await generate_invite_link(email, redirect_to)
    except SupabaseAdminError as exc:
        await session.rollback()
        # An already-registered email is a DUPLICATE, not an outage. The
        # per-advisor unique index (above) catches "this advisor's client";
        # this catches the wider case — another advisor's client, or any
        # existing auth user — where GoTrue rejects the invite with 422
        # ``email_exists``. Surface it on the duplicate path so the advisor
        # sees "already exists" rather than a misleading "auth unreachable".
        if exc.error_code == "email_exists" or exc.status_code == 422:
            logger.info(
                "clients.create.duplicate_email_registered",
                extra={"email": email, "advisor_id": str(advisor_id)},
            )
            return ClientCreateResult(ClientCreateOutcome.DUPLICATE_EMAIL)
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

    # The welcome link went out — stamp the invite time so the client reads as
    # ``pending`` (invited, awaiting first login) rather than ``uninvited``.
    client.invited_at = now
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

    accepted_at = datetime.now(UTC)
    try:
        await session.execute(
            update(Client)
            .where(Client.id == row.id, Client.auth_user_id.is_(None))
            .values(auth_user_id=user_id, accepted_at=accepted_at)
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
    row.accepted_at = accepted_at
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


async def resend_welcome_email(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    settings: Settings | None = None,
) -> ResendWelcomeResult:
    """Issue (or re-issue) the welcome sign-in link to a not-yet-signed-in client.

    Doubles as the **invite-later** action (ADV-1): it sends the *first*
    welcome link to an ``uninvited`` client (created silently) as well as
    *re-sending* it to a ``pending`` one. Loads the advisor-scoped client and,
    while they haven't accepted (``auth_user_id IS NULL``), asks Supabase to
    issue the invite/welcome link via :func:`generate_invite_link`. Once a
    client has accepted (``auth_user_id`` set on first login) there is nothing
    to send — they use the normal ``/auth/login`` magic-link flow — so we
    refuse with ``ALREADY_ACCEPTED``.

    On success, stamps ``invited_at`` the first time (flipping ``uninvited`` →
    ``pending``); a re-send to an already-invited client keeps its original
    ``invited_at`` and does no DB write.
    """
    settings = settings or get_settings()

    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return ResendWelcomeResult(ResendWelcomeOutcome.CLIENT_NOT_FOUND)

    if client.auth_user_id is not None:
        logger.info(
            "clients.resend_welcome.already_accepted",
            extra={"client_id": str(client_id), "advisor_id": str(advisor_id)},
        )
        return ResendWelcomeResult(ResendWelcomeOutcome.ALREADY_ACCEPTED)

    redirect_to = f"{settings.web_origin.rstrip('/')}/auth/callback?next=/basecamp"
    try:
        issued = await generate_invite_link(client.email, redirect_to)
    except SupabaseAdminError as exc:
        logger.warning(
            "clients.resend_welcome.admin_failure",
            extra={
                "client_id": str(client_id),
                "advisor_id": str(advisor_id),
                "reason": exc.reason,
                "status": exc.status_code,
            },
        )
        return ResendWelcomeResult(ResendWelcomeOutcome.UPSTREAM_UNAVAILABLE)

    # First invite of a silently-created client → stamp the invite time so it
    # flips ``uninvited`` → ``pending``. A re-send keeps the original stamp.
    if client.invited_at is None:
        client.invited_at = datetime.now(UTC)
        await session.commit()

    logger.info(
        "clients.resend_welcome.ok",
        extra={"client_id": str(client_id), "advisor_id": str(advisor_id)},
    )
    return ResendWelcomeResult(ResendWelcomeOutcome.OK, issued=issued)
