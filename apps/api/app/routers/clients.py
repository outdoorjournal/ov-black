"""Advisor-facing /clients surface (M001/S03 T05).

Five routes, all gated by :func:`app.auth_guards.require_advisor`:

- ``POST   /clients``                           create client + Voodoo Doll + invite (atomic)
- ``GET    /clients``                           advisor's own clients, newest-first
- ``GET    /clients/{id}``                      full client + Voodoo Doll payload + invite history
- ``POST   /clients/{id}/invite/reissue``       supersede the live invite and email a fresh one
- ``POST   /clients/{id}/invite/cancel``        mark the live invite cancelled (no email)

The POST path delegates to :func:`create_client_with_voodoo_doll` and maps
``ClientCreateOutcome`` to HTTP status codes the same way ``routers/auth.py``
maps ``RedeemOutcome`` — 201 / 409 / 502, with the 502 ``detail`` string
(``auth_upstream_unavailable``) deliberately reused from S01 so ops
dashboards can collapse both paths under one alert.

GET paths scope by ``owner_id = advisor_id``. ``GET /{client_id}`` 404s
whenever the row does not belong to the calling advisor (S01 D015
collapsed-shape precedent — 403 would let one advisor probe for another
advisor's client UUIDs). Invite status is derived from every row joining
``invites`` on ``(email, role='client', created_by=advisor_id)`` — after
the 0007 lifecycle migration, multiple rows may exist per client (one per
send), and the latest non-consumed row decides the rendered status.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, Invite, UserRole, VoodooDoll
from app.schemas.clients import (
    ClientCreatePayload,
    ClientCreateResponse,
    ClientDetail,
    ClientSummary,
    InviteEvent,
    InviteEventStatus,
    InviteStatus,
    VoodooDollDetail,
)
from app.services.clients import (
    ClientCreateOutcome,
    InviteCancelOutcome,
    InviteReissueOutcome,
    cancel_client_invite,
    create_client_with_voodoo_doll,
    reissue_client_invite,
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

    One query instead of a per-client lookup. For a fresh advisor this is
    a handful of rows; for a seasoned one it scales with lifetime clients,
    which is still trivial compared to the itinerary graph. If that ever
    stops being true we can move to a lateral join — the grouping lives
    in the router so the SQL stays simple.
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

    # Clients + Voodoo Doll presence in one query; invites fetched separately
    # and grouped in Python so multiple-row-per-client histories don't blow
    # up the join into N×M.
    stmt = (
        select(Client, VoodooDoll.id)
        .outerjoin(VoodooDoll, VoodooDoll.client_id == Client.id)
        .where(Client.owner_id == advisor_id)
        .order_by(Client.created_at.desc())
    )
    result = await session.execute(stmt)
    client_rows = result.all()

    invites_by_email = await _load_invites_for_advisor(session, advisor_id)

    rows: list[ClientSummary] = []
    for client, doll_id in client_rows:
        invites = invites_by_email.get(client.email, [])
        rows.append(
            ClientSummary(
                id=client.id,
                full_name=client.full_name,
                email=client.email,
                has_voodoo_doll=doll_id is not None,
                invite_status=_derive_invite_status(invites),
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

    invites_result = await session.execute(
        select(Invite).where(
            Invite.email == client.email,
            Invite.role == UserRole.client,
            Invite.created_by == advisor_id,
        )
    )
    invites = list(invites_result.scalars())

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
        invite_status=_derive_invite_status(invites),
        invite_history=_build_invite_history(invites),
        created_at=client.created_at,
        updated_at=client.updated_at,
        voodoo_doll=voodoo_payload,
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
