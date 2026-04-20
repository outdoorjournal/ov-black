"""Advisor-facing /clients surface (M001/S03 T05).

Three routes, all gated by :func:`app.auth_guards.require_advisor`:

- ``POST /clients``           create client + Voodoo Doll + invite (atomic)
- ``GET  /clients``           advisor's own clients, newest-first
- ``GET  /clients/{id}``      full client + Voodoo Doll payload

The POST path delegates to :func:`create_client_with_voodoo_doll` and maps
``ClientCreateOutcome`` to HTTP status codes the same way ``routers/auth.py``
maps ``RedeemOutcome`` — 201 / 409 / 502, with the 502 ``detail`` string
(``auth_upstream_unavailable``) deliberately reused from S01 so ops
dashboards can collapse both paths under one alert.

GET paths scope by ``owner_id = advisor_id``. ``GET /{client_id}`` 404s
whenever the row does not belong to the calling advisor (S01 D015
collapsed-shape precedent — 403 would let one advisor probe for another
advisor's client UUIDs). The invite status is derived by joining
``invites`` on ``(email, role='client', created_by=advisor_id)``.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, Invite, UserRole, VoodooDoll
from app.schemas.clients import (
    ClientCreatePayload,
    ClientCreateResponse,
    ClientDetail,
    ClientSummary,
    VoodooDollDetail,
)
from app.services.clients import (
    ClientCreateOutcome,
    create_client_with_voodoo_doll,
)

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


def _invite_status_for(
    invite: Invite | None,
) -> str:
    return "consumed" if invite is not None and invite.consumed_at is not None else "pending"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientCreateResponse,
    responses={
        201: {"description": "Client + Voodoo Doll created, invite email sent."},
        403: {"description": "Caller is not an advisor."},
        409: {"description": "Email is already tied to one of this advisor's clients."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Create a new client + Voodoo Doll and email them an invite link.",
)
async def create_client_endpoint(
    payload: ClientCreatePayload,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> ClientCreateResponse:
    advisor_id = _advisor_id(user)
    result = await create_client_with_voodoo_doll(
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

    # Left-join voodoo_dolls for the has_voodoo_doll flag and invites for
    # invite_status. The invite join is pinned to role='client' and
    # ``created_by = advisor_id`` so we only surface invites this advisor
    # issued for this specific client email.
    InviteAlias = aliased(Invite)
    DollAlias = aliased(VoodooDoll)
    stmt = (
        select(Client, DollAlias.id, InviteAlias)
        .outerjoin(DollAlias, DollAlias.client_id == Client.id)
        .outerjoin(
            InviteAlias,
            (InviteAlias.email == Client.email)
            & (InviteAlias.role == UserRole.client)
            & (InviteAlias.created_by == advisor_id),
        )
        .where(Client.owner_id == advisor_id)
        .order_by(Client.created_at.desc())
    )
    result = await session.execute(stmt)
    rows: list[ClientSummary] = []
    for client, doll_id, invite in result.all():
        rows.append(
            ClientSummary(
                id=client.id,
                full_name=client.full_name,
                email=client.email,
                has_voodoo_doll=doll_id is not None,
                invite_status=_invite_status_for(invite),
                created_at=client.created_at,
            )
        )
    return rows


@router.get(
    "/{client_id}",
    response_model=ClientDetail,
    responses={
        404: {"description": "No client with this id owned by the calling advisor."},
    },
    summary="Get a single client + Voodoo Doll by id (scoped to the caller).",
)
async def get_client_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
) -> ClientDetail:
    advisor_id = _advisor_id(user)

    client_result = await session.execute(
        select(Client).where(
            Client.id == client_id, Client.owner_id == advisor_id
        )
    )
    client = client_result.scalar_one_or_none()
    if client is None:
        # Collapsed shape (S01 D015) — never 403 on cross-advisor, that
        # leaks existence of the client_id to a probing advisor.
        raise HTTPException(status_code=404, detail="client_not_found")

    doll_result = await session.execute(
        select(VoodooDoll).where(VoodooDoll.client_id == client.id)
    )
    doll = doll_result.scalar_one_or_none()

    invite_result = await session.execute(
        select(Invite).where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
        )
    )
    invite = invite_result.scalar_one_or_none()

    voodoo_payload: VoodooDollDetail | None = None
    if doll is not None:
        voodoo_payload = VoodooDollDetail(
            id=doll.id,
            contact_preference=doll.contact_preference,
            group_type=doll.group_type,
            children_ages=list(doll.children_ages),
            travel_party_notes=doll.travel_party_notes,
            estimated_net_worth_usd=doll.estimated_net_worth_usd,
            passions=list(doll.passions),
            motivations=dict(doll.motivations),
            travel_history=list(doll.travel_history),
            triggers=list(doll.triggers),
            constraints=list(doll.constraints),
            deal_breakers=list(doll.deal_breakers),
            dream_trip_signals=dict(doll.dream_trip_signals),
            osint_notes=dict(doll.osint_notes),
            created_at=doll.created_at,
            updated_at=doll.updated_at,
        )

    return ClientDetail(
        id=client.id,
        full_name=client.full_name,
        email=client.email,
        invite_status=_invite_status_for(invite),
        created_at=client.created_at,
        updated_at=client.updated_at,
        voodoo_doll=voodoo_payload,
    )
