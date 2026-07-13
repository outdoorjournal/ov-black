"""Advisor-facing /clients surface (M001/S03 T05).

Five routes, all gated by :func:`app.auth_guards.require_advisor`:

- ``POST   /clients`` — create client + Dossier (+ optional dossier_facts) and
  email a welcome sign-in link (atomic)
- ``GET    /clients`` — advisor's own clients, newest-first
- ``GET    /clients/{id}`` — client + dossier + active facts (``?include_redacted=1`` opt-in)
- ``POST   /clients/{id}/resend-welcome`` — re-send the welcome link to a pending client

The POST path delegates to :func:`create_client_with_dossier` and maps
``ClientCreateOutcome`` to HTTP status codes — 201 / 409 / 502, with the 502
``detail`` string (``auth_upstream_unavailable``) shared with ``/auth/login``
so ops dashboards can collapse both paths under one alert.

GET paths scope by ``owner_id = advisor_id``. ``GET /{client_id}`` 404s
whenever the row does not belong to the calling advisor (S01 D015
collapsed-shape precedent — 403 would let one advisor probe for another
advisor's client UUIDs).

A client's ``access_status`` is derived from ``clients.auth_user_id``:
``pending`` until they sign in for the first time (which backfills the id via
``resolve_client_for_auth_user``), ``active`` after.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import uuid
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import (
    AgentSession,
    AgentTurn,
    Client,
    Dossier,
    TurnRole,
)
from app.schemas.clients import (
    AccessStatus,
    ClientCreatePayload,
    ClientCreateResponse,
    ClientDetail,
    ClientsPage,
    ClientSummary,
    ClientUpdatePayload,
)
from app.schemas.contacts import (
    ClientContactCreate,
    ClientContactDetail,
    ClientContactUpdate,
)
from app.schemas.dossier import DossierDetail
from app.schemas.facts import (
    DossierFactDetail,
    OsintFactDetail,
    ProfileFactDetail,
)
from app.services.clients import (
    ClientCreateOutcome,
    ResendWelcomeOutcome,
    create_client_with_dossier,
    resend_welcome_email,
)
from app.services.contacts import (
    ContactOutcome,
    create_client_contact,
    delete_client_contact,
    list_client_contacts,
    update_client_contact,
)
from app.services.facts import load_agent_context
from app.services.pagination import clamp_limit, encode_cursor, require_cursor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.clients")


class ClientSessionSummary(BaseModel):
    """Row shape for ``GET /clients/{id}/sessions`` — one agent session."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    started_at: _datetime.datetime
    ended_at: _datetime.datetime | None
    last_turn_at: _datetime.datetime | None
    turn_count: int
    itinerary_id: uuid.UUID | None
    seeded_opener: str | None


class ClientSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[ClientSessionSummary]


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


def _access_status(client: Client) -> AccessStatus:
    """Render a client's place on the invite → sign-in path.

    ``active`` once the client signs in for the first time (which backfills
    ``auth_user_id`` via ``resolve_client_for_auth_user``); otherwise
    ``pending`` if the welcome link has been issued (``invited_at`` set), or
    ``uninvited`` if the client was created silently and never notified.
    """
    if client.auth_user_id is not None:
        return "active"
    if client.invited_at is not None:
        return "pending"
    return "uninvited"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientCreateResponse,
    responses={
        201: {
            "description": (
                "Client + Dossier created. A welcome sign-in link is emailed "
                "unless ``notify=false`` (silent create — invite later)."
            )
        },
        403: {"description": "Caller is not an advisor."},
        409: {"description": "Email already exists — a client, or an already-registered account."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Create a new client + Dossier; email a welcome link unless notify=false.",
)
async def create_client_endpoint(
    payload: ClientCreatePayload,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientCreateResponse:
    advisor_id = _advisor_id(user)
    result = await create_client_with_dossier(session, advisor_id=advisor_id, payload=payload)

    if result.outcome is ClientCreateOutcome.OK:
        assert result.client_id is not None  # guaranteed by OK contract
        return ClientCreateResponse(
            client_id=result.client_id,
            email=payload.email,
        )
    if result.outcome is ClientCreateOutcome.DUPLICATE_EMAIL:
        raise HTTPException(status_code=409, detail="client_email_already_invited")
    if result.outcome is ClientCreateOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    # Defensive — every enum value is handled above.
    logger.error("clients.router.unhandled_outcome", extra={"outcome": result.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")


def _escape_like(q: str) -> str:
    """Escape ILIKE wildcards so a literal ``%``/``_`` in the query stays literal."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _status_predicate(status: AccessStatus) -> Any:
    """The _access_status truth table as a SQL predicate."""
    if status == "active":
        return Client.auth_user_id.is_not(None)
    if status == "pending":
        return and_(Client.auth_user_id.is_(None), Client.invited_at.is_not(None))
    return and_(Client.auth_user_id.is_(None), Client.invited_at.is_(None))


@router.get(
    "",
    response_model=ClientsPage,
    summary="Search/page the calling advisor's clients.",
)
async def list_clients_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    cursor: str | None = None,
    q: str | None = None,
    status: AccessStatus | None = None,
    sort: Literal["created_at", "full_name"] = "created_at",
    order: Literal["asc", "desc"] | None = None,
) -> ClientsPage:
    """Wave F: the roster is an envelope (``{clients, next_cursor, total}``)
    with substring search, status filter, and keyset paging. No params →
    first page of 50, newest first (the pre-Wave-F ordering).
    """
    advisor_id = _advisor_id(user)
    page_limit = clamp_limit(limit)
    # created_at reads naturally newest-first; names read A→Z.
    direction = order or ("desc" if sort == "created_at" else "asc")
    sort_col = Client.created_at if sort == "created_at" else Client.full_name

    filters: list[Any] = [Client.owner_id == advisor_id]
    if q:
        needle = f"%{_escape_like(q)}%"
        filters.append(
            or_(
                Client.full_name.ilike(needle, escape="\\"),
                Client.email.ilike(needle, escape="\\"),
            )
        )
    if status is not None:
        filters.append(_status_predicate(status))

    total = int((await session.execute(select(func.count(Client.id)).where(*filters))).scalar_one())

    stmt = (
        select(Client, Dossier.id)
        .outerjoin(Dossier, Dossier.client_id == Client.id)
        .where(*filters)
    )
    payload = require_cursor(cursor)
    if payload is not None:
        cur_id = uuid.UUID(str(payload["id"]))
        raw_v = str(payload["v"])
        cur_v: Any = _datetime.datetime.fromisoformat(raw_v) if sort == "created_at" else raw_v
        if direction == "desc":
            stmt = stmt.where(or_(sort_col < cur_v, and_(sort_col == cur_v, Client.id > cur_id)))
        else:
            stmt = stmt.where(or_(sort_col > cur_v, and_(sort_col == cur_v, Client.id > cur_id)))
    ordered = sort_col.desc() if direction == "desc" else sort_col.asc()
    stmt = stmt.order_by(ordered, Client.id.asc()).limit(page_limit)
    client_rows = (await session.execute(stmt)).all()

    rows: list[ClientSummary] = []
    for client, dossier_id in client_rows:
        rows.append(
            ClientSummary(
                id=client.id,
                full_name=client.full_name,
                email=client.email,
                has_dossier=dossier_id is not None,
                access_status=_access_status(client),
                invited_at=client.invited_at,
                accepted_at=client.accepted_at,
                created_at=client.created_at,
            )
        )

    next_cursor: str | None = None
    if len(client_rows) == page_limit and client_rows:
        last_client = client_rows[-1][0]
        last_v = (
            last_client.created_at.isoformat() if sort == "created_at" else last_client.full_name
        )
        next_cursor = encode_cursor({"v": last_v, "id": str(last_client.id)})

    return ClientsPage(clients=rows, next_cursor=next_cursor, total=total)


def _dossier_detail(dossier: Dossier | None) -> DossierDetail | None:
    if dossier is None:
        return None
    return DossierDetail(
        id=dossier.id,
        contact_preference=dossier.contact_preference,
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
    session: AsyncSession = Depends(get_session),
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
        select(Client).where(Client.id == client_id, Client.owner_id == advisor_id)
    )
    client = client_result.scalar_one_or_none()
    if client is None:
        # Collapsed shape (S01 D015) — never 403 on cross-advisor.
        raise HTTPException(status_code=404, detail="client_not_found")

    ctx = await load_agent_context(session, client_id=client.id, include_redacted=include_redacted)
    # ``ctx`` is None only if the client row vanished between the two
    # selects; treat that as a 404 to keep the shape consistent.
    if ctx is None:
        raise HTTPException(status_code=404, detail="client_not_found")

    contact_rows = await list_client_contacts(session, client_id=client.id)

    return ClientDetail(
        id=client.id,
        full_name=client.full_name,
        email=client.email,
        access_status=_access_status(client),
        invited_at=client.invited_at,
        accepted_at=client.accepted_at,
        created_at=client.created_at,
        updated_at=client.updated_at,
        address=client.address,
        favorite_airport=client.favorite_airport,
        preferred_currency=client.preferred_currency,
        city=client.city,
        region=client.region,
        postal_code=client.postal_code,
        country_code=client.country_code,
        dossier=_dossier_detail(ctx.dossier),
        dossier_facts=[
            DossierFactDetail.model_validate(f, from_attributes=True) for f in ctx.dossier_facts
        ],
        profile_facts=[
            ProfileFactDetail.model_validate(f, from_attributes=True) for f in ctx.profile_facts
        ],
        osint_facts=[
            OsintFactDetail.model_validate(f, from_attributes=True) for f in ctx.osint_facts
        ],
        contacts=[
            ClientContactDetail.model_validate(c, from_attributes=True) for c in contact_rows
        ],
    )


@router.patch(
    "/{client_id}",
    response_model=ClientDetail,
    responses={
        404: {"description": "No client with this id owned by the calling advisor."},
    },
    summary="Update a client's traveler-logistics fields (address, airport, currency).",
)
async def update_client_endpoint(
    client_id: uuid.UUID,
    payload: ClientUpdatePayload,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientDetail:
    advisor_id = _advisor_id(user)

    client_result = await session.execute(
        select(Client).where(Client.id == client_id, Client.owner_id == advisor_id)
    )
    client = client_result.scalar_one_or_none()
    if client is None:
        # Collapsed shape (S01 D015) — never 403 on cross-advisor.
        raise HTTPException(status_code=404, detail="client_not_found")

    # Only apply keys the caller actually sent, so an explicit null clears a
    # field while an omitted one is left untouched. Codes are stored upper-cased.
    provided = payload.model_fields_set
    if "address" in provided:
        client.address = payload.address
    if "favorite_airport" in provided:
        client.favorite_airport = (
            payload.favorite_airport.upper() if payload.favorite_airport else None
        )
    if "preferred_currency" in provided:
        client.preferred_currency = (
            payload.preferred_currency.upper() if payload.preferred_currency else None
        )
    if "city" in provided:
        client.city = payload.city
    if "region" in provided:
        client.region = payload.region
    if "postal_code" in provided:
        client.postal_code = payload.postal_code
    if "country_code" in provided:
        client.country_code = payload.country_code.upper() if payload.country_code else None

    await session.flush()
    await session.commit()

    return await get_client_endpoint(
        client_id=client_id, user=user, session=session, include_redacted=False
    )


@router.post(
    "/{client_id}/resend-welcome",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Welcome sign-in link re-sent."},
        404: {"description": "No client with this id owned by the calling advisor."},
        409: {"description": "Client has already signed in — nothing to resend."},
        502: {"description": "Supabase Auth admin API is unavailable."},
    },
    summary="Re-send the welcome sign-in link to a pending client.",
)
async def resend_welcome_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    advisor_id = _advisor_id(user)
    result = await resend_welcome_email(session, advisor_id=advisor_id, client_id=client_id)

    if result.outcome is ResendWelcomeOutcome.OK:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if result.outcome is ResendWelcomeOutcome.CLIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="client_not_found")
    if result.outcome is ResendWelcomeOutcome.ALREADY_ACCEPTED:
        raise HTTPException(status_code=409, detail="client_already_accepted")
    if result.outcome is ResendWelcomeOutcome.UPSTREAM_UNAVAILABLE:
        raise HTTPException(status_code=502, detail="auth_upstream_unavailable")
    logger.error(
        "clients.router.resend_welcome_unhandled_outcome",
        extra={"outcome": result.outcome.value},
    )
    raise HTTPException(status_code=500, detail="internal_error")


@router.get(
    "/{client_id}/sessions",
    response_model=ClientSessionsResponse,
    responses={
        404: {"description": "No client with this id owned by the calling advisor."},
    },
    summary="List the calling advisor's view of every agent session for one client.",
)
async def list_client_sessions_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientSessionsResponse:
    advisor_id = _advisor_id(user)

    owned = (
        await session.execute(
            select(Client.id).where(
                Client.id == client_id,
                Client.owner_id == advisor_id,
            )
        )
    ).scalar_one_or_none()
    if owned is None:
        # Collapsed-shape (D015) — never 403 on cross-advisor.
        raise HTTPException(status_code=404, detail="client_not_found")

    # One left-join with grouped aggregates so the table renders without an N+1.
    # Only user/assistant turns count toward turn_count and last_turn_at —
    # system/tool/error rows are noise from the advisor's perspective.
    stmt = (
        select(
            AgentSession,
            func.count(AgentTurn.id).label("turn_count"),
            func.max(AgentTurn.created_at).label("last_turn_at"),
        )
        .outerjoin(
            AgentTurn,
            (AgentTurn.session_id == AgentSession.id)
            & (AgentTurn.role.in_((TurnRole.user, TurnRole.assistant))),
        )
        .where(AgentSession.client_id == client_id)
        .group_by(AgentSession.id)
        .order_by(AgentSession.started_at.desc())
    )
    rows = (await session.execute(stmt)).all()

    return ClientSessionsResponse(
        sessions=[
            ClientSessionSummary(
                id=row[0].id,
                started_at=row[0].started_at,
                ended_at=row[0].ended_at,
                last_turn_at=row[2],
                turn_count=int(row[1] or 0),
                itinerary_id=row[0].itinerary_id,
                seeded_opener=row[0].seeded_opener,
            )
            for row in rows
        ]
    )


# ── Contacts ─────────────────────────────────────────────────────────────


def _raise_for_contact_outcome(outcome: ContactOutcome) -> None:
    if outcome is ContactOutcome.CLIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="client_not_found")
    if outcome is ContactOutcome.CONTACT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="contact_not_found")
    raise HTTPException(status_code=500, detail="internal_error")


@router.post(
    "/{client_id}/contacts",
    status_code=status.HTTP_201_CREATED,
    response_model=ClientContactDetail,
    responses={
        404: {"description": "No client with this id owned by the calling advisor."},
    },
    summary="Add a contact method (phone / messenger / social) to a client.",
)
async def create_client_contact_endpoint(
    client_id: uuid.UUID,
    payload: ClientContactCreate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientContactDetail:
    result = await create_client_contact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        payload=payload,
    )
    if result.outcome is not ContactOutcome.OK or result.contact is None:
        _raise_for_contact_outcome(result.outcome)
    return ClientContactDetail.model_validate(result.contact, from_attributes=True)


@router.patch(
    "/{client_id}/contacts/{contact_id}",
    response_model=ClientContactDetail,
    summary="Update an existing contact method.",
)
async def update_client_contact_endpoint(
    client_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: ClientContactUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientContactDetail:
    result = await update_client_contact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        contact_id=contact_id,
        payload=payload,
    )
    if result.outcome is not ContactOutcome.OK or result.contact is None:
        _raise_for_contact_outcome(result.outcome)
    return ClientContactDetail.model_validate(result.contact, from_attributes=True)


@router.delete(
    "/{client_id}/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a contact method (hard delete).",
)
async def delete_client_contact_endpoint(
    client_id: uuid.UUID,
    contact_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    outcome = await delete_client_contact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        contact_id=contact_id,
    )
    if outcome is not ContactOutcome.OK:
        _raise_for_contact_outcome(outcome)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
