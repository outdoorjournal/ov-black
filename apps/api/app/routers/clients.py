"""Advisor-facing /clients surface (M001/S03 T05).

Five routes, all gated by :func:`app.auth_guards.require_advisor`:

- ``POST   /clients``                           create client + Dossier (+ optional initial dossier_facts) + invite (atomic)
- ``GET    /clients``                           advisor's own clients, newest-first
- ``GET    /clients/{id}``                      full client + dossier + active facts (?include_redacted=1 to include redacted)
- ``POST   /clients/{id}/invite/reissue``       supersede the live invite and email a fresh one
- ``POST   /clients/{id}/invite/cancel``        mark the live invite cancelled (no email)

The POST path delegates to :func:`create_client_with_dossier` and maps
``ClientCreateOutcome`` to HTTP status codes the same way ``routers/auth.py``
maps ``RedeemOutcome`` — 201 / 409 / 502, with the 502 ``detail`` string
(``auth_upstream_unavailable``) deliberately reused from S01 so ops
dashboards can collapse both paths under one alert.

GET paths scope by ``owner_id = advisor_id``. ``GET /{client_id}`` 404s
whenever the row does not belong to the calling advisor (S01 D015
collapsed-shape precedent — 403 would let one advisor probe for another
advisor's client UUIDs).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, Dossier, Invite, UserRole
from app.schemas.clients import (
    ClientCreatePayload,
    ClientCreateResponse,
    ClientDetail,
    ClientSummary,
    InviteEvent,
    InviteEventStatus,
    InviteStatus,
)
from app.schemas.dossier import DossierDetail
from app.schemas.facts import (
    DossierFactDetail,
    OsintFactDetail,
    ProfileFactDetail,
)
from app.services.clients import (
    ClientCreateOutcome,
    InviteCancelOutcome,
    InviteReissueOutcome,
    cancel_client_invite,
    create_client_with_dossier,
    reissue_client_invite,
)
from app.services.facts import load_agent_context

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.clients")

router = APIRouter(prefix="/clients", tags=["clients"])


def _advisor_id(user: AuthenticatedUser) -> uuid.UUID:
    """Parse ``user.sub`` as a UUID.

    ``require_advisor`` has already verified the sub resolves to an advisor
    profile (which means the DB looked it up as a UUID), so this parse
    cannot fail in practice — but we keep a defensive 500 path rather than
    letting a ``ValueError`` bubble to a 500 with an ugly traceback.
    """
    try:
        return uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — guarded by require_advisor
        logger.error("clients.router.malformed_sub", extra={"sub_hint": user.sub[:8]})
        raise HTTPException(status_code=500, detail="internal_error") from None


def _event_status(invite: Invite) -> InviteEventStatus:
    if invite.consumed_at is not None:
        return "consumed"
    if invite.cancelled_at is not None:
        return "cancelled"
    if invite.superseded_at is not None:
        return "superseded"
    return "active"


def _derive_invite_status(invites: list[Invite]) -> InviteStatus:
    """Collapse a client's invite history to a single rendered status.

    Precedence:

    1. Any consumed row wins — the client has redeemed at some point.
    2. An active row (all three lifecycle timestamps NULL) → ``pending``.
    3. Otherwise, the most recent row is either cancelled or superseded;
       advisor-facing UI shows that as ``cancelled`` (there is no live
       invite out there, nothing to resend against).
    4. No rows at all → ``none`` (edge case — ``POST /clients`` always
       inserts one, but a data-recovery scenario could leave a client
       without a row).
    """
    if not invites:
        return "none"
    if any(inv.consumed_at is not None for inv in invites):
        return "consumed"
    if any(
        inv.consumed_at is None
        and inv.cancelled_at is None
        and inv.superseded_at is None
        for inv in invites
    ):
        return "pending"
    return "cancelled"


def _build_invite_history(invites: list[Invite]) -> list[InviteEvent]:
    """Newest-first history, one entry per ``invites`` row."""
    ordered = sorted(invites, key=lambda inv: inv.created_at, reverse=True)
    return [
        InviteEvent(
            created_at=inv.created_at,
            consumed_at=inv.consumed_at,
            cancelled_at=inv.cancelled_at,
            superseded_at=inv.superseded_at,
            status=_event_status(inv),
        )
        for inv in ordered
    ]


async def _load_invites_for_advisor(
    session: "AsyncSession",
    advisor_id: uuid.UUID,
) -> dict[str, list[Invite]]:
    """Fetch every client-role invite this advisor issued, grouped by email.

    One query instead of a per-client lookup.
    """
    result = await session.execute(
        select(Invite).where(
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
            Invite.email.is_not(None),
        )
    )
    by_email: dict[str, list[Invite]] = {}
    for invite in result.scalars():
        assert invite.email is not None  # guaranteed by WHERE clause
        by_email.setdefault(invite.email, []).append(invite)
    return by_email


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientCreateResponse,
    responses={
        201: {"description": "Client + Dossier created, invite email sent."},
        403: {"description": "Caller is not an advisor."},
        409: {"description": "Email is already tied to one of this advisor's clients."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Create a new client + Dossier and email them an invite link.",
)
async def create_client_endpoint(
    payload: ClientCreatePayload,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> ClientCreateResponse:
    advisor_id = _advisor_id(user)
    result = await create_client_with_dossier(
        session, advisor_id=advisor_id, payload=payload
    )

    if result.outcome is ClientCreateOutcome.OK:
        assert result.client_id is not None  # guaranteed by OK contract
        return ClientCreateResponse(
            client_id=result.client_id,
            invite_email=payload.email,
        )
    if result.outcome is ClientCreateOutcome.DUPLICATE_EMAIL:
        raise HTTPException(status_code=409, detail="client_email_already_invited")
    if result.outcome is ClientCreateOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    # Defensive — every enum value is handled above.
    logger.error(
        "clients.router.unhandled_outcome", extra={"outcome": result.outcome.value}
    )
    raise HTTPException(status_code=500, detail="internal_error")


@router.get(
    "",
    response_model=list[ClientSummary],
    summary="List the calling advisor's clients, newest first.",
)
async def list_clients_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> list[ClientSummary]:
    advisor_id = _advisor_id(user)

    stmt = (
        select(Client, Dossier.id)
        .outerjoin(Dossier, Dossier.client_id == Client.id)
        .where(Client.owner_id == advisor_id)
        .order_by(Client.created_at.desc())
    )
    result = await session.execute(stmt)
    client_rows = result.all()

    invites_by_email = await _load_invites_for_advisor(session, advisor_id)

    rows: list[ClientSummary] = []
    for client, dossier_id in client_rows:
        invites = invites_by_email.get(client.email, [])
        rows.append(
            ClientSummary(
                id=client.id,
                full_name=client.full_name,
                email=client.email,
                has_dossier=dossier_id is not None,
                invite_status=_derive_invite_status(invites),
                created_at=client.created_at,
            )
        )
    return rows


def _dossier_detail(dossier: Dossier | None) -> DossierDetail | None:
    if dossier is None:
        return None
    return DossierDetail(
        id=dossier.id,
        contact_preference=dossier.contact_preference,
        group_type=dossier.group_type,
        children_ages=list(dossier.children_ages),
        travel_party_notes=dossier.travel_party_notes,
        estimated_net_worth_usd=dossier.estimated_net_worth_usd,
        created_at=dossier.created_at,
        updated_at=dossier.updated_at,
    )


@router.get(
    "/{client_id}",
    response_model=ClientDetail,
    responses={
        404: {"description": "No client with this id owned by the calling advisor."},
    },
    summary="Get a single client + Dossier + per-tier facts (scoped to the caller).",
)
async def get_client_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
    include_redacted: bool = Query(
        default=False,
        description=(
            "When true, redacted facts are included in the response so "
            "advisors can review and (in a later slice) restore them. "
            "Default false hides redactions from normal review."
        ),
    ),
) -> ClientDetail:
    advisor_id = _advisor_id(user)

    client_result = await session.execute(
        select(Client).where(
            Client.id == client_id, Client.owner_id == advisor_id
        )
    )
    client = client_result.scalar_one_or_none()
    if client is None:
        # Collapsed shape (S01 D015) — never 403 on cross-advisor.
        raise HTTPException(status_code=404, detail="client_not_found")

    ctx = await load_agent_context(
        session, client_id=client.id, include_redacted=include_redacted
    )
    # ``ctx`` is None only if the client row vanished between the two
    # selects; treat that as a 404 to keep the shape consistent.
    if ctx is None:
        raise HTTPException(status_code=404, detail="client_not_found")

    invites_result = await session.execute(
        select(Invite).where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
        )
    )
    invites = list(invites_result.scalars())

    return ClientDetail(
        id=client.id,
        full_name=client.full_name,
        email=client.email,
        invite_status=_derive_invite_status(invites),
        invite_history=_build_invite_history(invites),
        created_at=client.created_at,
        updated_at=client.updated_at,
        dossier=_dossier_detail(ctx.dossier),
        dossier_facts=[DossierFactDetail.model_validate(f, from_attributes=True) for f in ctx.dossier_facts],
        profile_facts=[ProfileFactDetail.model_validate(f, from_attributes=True) for f in ctx.profile_facts],
        osint_facts=[OsintFactDetail.model_validate(f, from_attributes=True) for f in ctx.osint_facts],
    )


@router.post(
    "/{client_id}/invite/reissue",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "New invite issued and email sent."},
        404: {"description": "No client with this id owned by the calling advisor."},
        409: {"description": "Client already redeemed — reissue is not allowed."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Supersede the live invite for a client and email a fresh one.",
)
async def reissue_client_invite_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> Response:
    advisor_id = _advisor_id(user)
    result = await reissue_client_invite(
        session, advisor_id=advisor_id, client_id=client_id
    )

    if result.outcome is InviteReissueOutcome.OK:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if result.outcome is InviteReissueOutcome.CLIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="client_not_found")
    if result.outcome is InviteReissueOutcome.ALREADY_REDEEMED:
        raise HTTPException(status_code=409, detail="invite_already_redeemed")
    if result.outcome is InviteReissueOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    logger.error(
        "clients.router.reissue_unhandled_outcome",
        extra={"outcome": result.outcome.value},
    )
    raise HTTPException(status_code=500, detail="internal_error")


@router.post(
    "/{client_id}/invite/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Active invite marked cancelled."},
        404: {"description": "No client with this id owned by the calling advisor."},
        409: {
            "description": (
                "No active invite to cancel — client is already redeemed or "
                "the outstanding invite was already cancelled/superseded."
            ),
        },
    },
    summary="Cancel the active invite for a client (no email sent).",
)
async def cancel_client_invite_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> Response:
    advisor_id = _advisor_id(user)
    result = await cancel_client_invite(
        session, advisor_id=advisor_id, client_id=client_id
    )

    if result.outcome is InviteCancelOutcome.OK:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if result.outcome is InviteCancelOutcome.CLIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="client_not_found")
    if result.outcome is InviteCancelOutcome.NO_ACTIVE_INVITE:
        raise HTTPException(status_code=409, detail="no_active_invite")
    logger.error(
        "clients.router.cancel_unhandled_outcome",
        extra={"outcome": result.outcome.value},
    )
    raise HTTPException(status_code=500, detail="internal_error")
