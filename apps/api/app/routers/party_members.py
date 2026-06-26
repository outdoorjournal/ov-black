"""Party member surfaces — the collaborative roster (M003/V1).

Three actors maintain the same durable, household-scoped members (0019), so this
router exposes parallel surfaces that all funnel into ``services.party_members``:

- **Advisor** (``/clients/{id}/party-members``, ``require_advisor``) — scoped to
  clients the advisor owns; writes stamp ``actor=advisor``.
- **Traveler** (``/me/party-members``, ``require_user``) — the caller's own
  household, resolved from their Supabase identity; writes stamp ``actor=traveler``.
- **Per-trip** (``/itineraries/{id}/party``) — attach/detach a saved member onto a
  trip, authorized by access to the itinerary's client (advisor OR linked
  traveler).

The agent's write path lives in ``routers/agent_internal.py`` (it authenticates
with the per-session token, not a Supabase JWT). All four 404 the D015 way on a
client/itinerary the caller can't touch — no 403 that would confirm existence.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, PartyMember, PartyMemberActor
from app.schemas.party_members import (
    AttachPartyMemberRequest,
    ItineraryPartyEntry,
    ItineraryPartyResponse,
    PartyMemberCreate,
    PartyMemberDetail,
    PartyMemberListResponse,
    PartyMemberUpdate,
)
from app.services.clients import resolve_client_for_auth_user
from app.services.party_members import (
    archive_party_member,
    attach_member_to_itinerary,
    create_party_member,
    detach_member_from_itinerary,
    get_party_member,
    list_itinerary_party,
    list_party_members,
    load_client_for_advisor,
    load_itinerary_client_id,
    update_party_member,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("ov_black.routers.party_members")

router = APIRouter(tags=["party-members"])

_NOT_FOUND = HTTPException(status_code=404, detail="client_not_found")
_ITIN_NOT_FOUND = HTTPException(status_code=404, detail="itinerary_not_found")
_MEMBER_NOT_FOUND = HTTPException(status_code=404, detail="party_member_not_found")


def _uid(user: AuthenticatedUser) -> uuid.UUID:
    try:
        return uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        raise _NOT_FOUND from None


def _detail(member: PartyMember) -> PartyMemberDetail:
    return PartyMemberDetail.model_validate(member)


# ── shared resolution ────────────────────────────────────────────────────


async def _resolve_traveler_client(
    session: AsyncSession, user: AuthenticatedUser
) -> Client:
    """The client the calling traveler belongs to, or 404."""
    client = await resolve_client_for_auth_user(
        session, user_id=_uid(user), email=user.email
    )
    if client is None:
        raise _NOT_FOUND
    return client


async def _authorize_itinerary_client(
    session: AsyncSession, user: AuthenticatedUser, itinerary_id: uuid.UUID
) -> uuid.UUID:
    """The itinerary's client_id iff the caller (advisor OR traveler) may touch it."""
    client_id = await load_itinerary_client_id(session, itinerary_id=itinerary_id)
    if client_id is None:
        raise _ITIN_NOT_FOUND
    client = await session.get(Client, client_id)
    if client is None:  # pragma: no cover — FK guarantees presence
        raise _ITIN_NOT_FOUND
    uid = _uid(user)
    if client.owner_id == uid:
        return client_id
    own = await resolve_client_for_auth_user(session, user_id=uid, email=user.email)
    if own is not None and own.id == client_id:
        return client_id
    raise _ITIN_NOT_FOUND


# ── advisor surface ──────────────────────────────────────────────────────


@router.get(
    "/clients/{client_id}/party-members",
    response_model=PartyMemberListResponse,
    summary="List a client's saved party members (advisor).",
)
async def list_client_party_members_endpoint(
    client_id: uuid.UUID,
    include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberListResponse:
    if await load_client_for_advisor(session, advisor_id=_uid(user), client_id=client_id) is None:
        raise _NOT_FOUND
    members = await list_party_members(
        session, client_id=client_id, include_archived=include_archived
    )
    return PartyMemberListResponse(members=[_detail(m) for m in members])


@router.post(
    "/clients/{client_id}/party-members",
    response_model=PartyMemberDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a party member to a client's household (advisor).",
)
async def create_client_party_member_endpoint(
    client_id: uuid.UUID,
    payload: PartyMemberCreate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    advisor_id = _uid(user)
    if await load_client_for_advisor(session, advisor_id=advisor_id, client_id=client_id) is None:
        raise _NOT_FOUND
    member = await create_party_member(
        session,
        client_id=client_id,
        payload=payload,
        actor=PartyMemberActor.advisor,
        recorded_by=advisor_id,
    )
    return _detail(member)


@router.patch(
    "/clients/{client_id}/party-members/{member_id}",
    response_model=PartyMemberDetail,
    summary="Edit a client's party member (advisor).",
)
async def update_client_party_member_endpoint(
    client_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: PartyMemberUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    if await load_client_for_advisor(session, advisor_id=_uid(user), client_id=client_id) is None:
        raise _NOT_FOUND
    member = await update_party_member(
        session,
        client_id=client_id,
        member_id=member_id,
        payload=payload,
        actor=PartyMemberActor.advisor,
    )
    if member is None:
        raise _MEMBER_NOT_FOUND
    return _detail(member)


@router.delete(
    "/clients/{client_id}/party-members/{member_id}",
    response_model=PartyMemberDetail,
    summary="Archive a client's party member (advisor).",
)
async def archive_client_party_member_endpoint(
    client_id: uuid.UUID,
    member_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    if await load_client_for_advisor(session, advisor_id=_uid(user), client_id=client_id) is None:
        raise _NOT_FOUND
    member = await archive_party_member(session, client_id=client_id, member_id=member_id)
    if member is None:
        raise _MEMBER_NOT_FOUND
    return _detail(member)


# ── traveler self-service surface ────────────────────────────────────────


@router.get(
    "/me/party-members",
    response_model=PartyMemberListResponse,
    summary="List my own household's party members (traveler).",
)
async def list_my_party_members_endpoint(
    include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberListResponse:
    client = await _resolve_traveler_client(session, user)
    members = await list_party_members(
        session, client_id=client.id, include_archived=include_archived
    )
    return PartyMemberListResponse(members=[_detail(m) for m in members])


@router.post(
    "/me/party-members",
    response_model=PartyMemberDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a party member to my own household (traveler).",
)
async def create_my_party_member_endpoint(
    payload: PartyMemberCreate,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    client = await _resolve_traveler_client(session, user)
    member = await create_party_member(
        session,
        client_id=client.id,
        payload=payload,
        actor=PartyMemberActor.traveler,
        recorded_by=_uid(user),
    )
    return _detail(member)


@router.patch(
    "/me/party-members/{member_id}",
    response_model=PartyMemberDetail,
    summary="Edit one of my own party members (traveler).",
)
async def update_my_party_member_endpoint(
    member_id: uuid.UUID,
    payload: PartyMemberUpdate,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    client = await _resolve_traveler_client(session, user)
    member = await update_party_member(
        session,
        client_id=client.id,
        member_id=member_id,
        payload=payload,
        actor=PartyMemberActor.traveler,
    )
    if member is None:
        raise _MEMBER_NOT_FOUND
    return _detail(member)


@router.delete(
    "/me/party-members/{member_id}",
    response_model=PartyMemberDetail,
    summary="Archive one of my own party members (traveler).",
)
async def archive_my_party_member_endpoint(
    member_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    client = await _resolve_traveler_client(session, user)
    member = await archive_party_member(session, client_id=client.id, member_id=member_id)
    if member is None:
        raise _MEMBER_NOT_FOUND
    return _detail(member)


# ── per-trip participation (who's traveling) ─────────────────────────────


@router.get(
    "/itineraries/{itinerary_id}/party",
    response_model=ItineraryPartyResponse,
    summary="Who's traveling on this itinerary (advisor or linked traveler).",
)
async def list_itinerary_party_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryPartyResponse:
    await _authorize_itinerary_client(session, user, itinerary_id)
    rows = await list_itinerary_party(session, itinerary_id=itinerary_id)
    return ItineraryPartyResponse(
        itinerary_id=itinerary_id,
        members=[
            ItineraryPartyEntry(
                traveler_id=traveler.id,
                party_id=traveler.party_id,
                name=traveler.name,
                party_member_id=traveler.party_member_id,
                member=_detail(member) if member is not None else None,
            )
            for traveler, member in rows
        ],
    )


@router.post(
    "/itineraries/{itinerary_id}/party/members",
    response_model=ItineraryPartyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a saved party member to this itinerary's party.",
)
async def attach_itinerary_party_member_endpoint(
    itinerary_id: uuid.UUID,
    payload: AttachPartyMemberRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryPartyResponse:
    client_id = await _authorize_itinerary_client(session, user, itinerary_id)
    member = await get_party_member(
        session, client_id=client_id, member_id=payload.party_member_id
    )
    if member is None:
        # The member must belong to this itinerary's household.
        raise _MEMBER_NOT_FOUND
    await attach_member_to_itinerary(session, itinerary_id=itinerary_id, member=member)
    return await list_itinerary_party_endpoint(itinerary_id, user=user, session=session)


@router.delete(
    "/itineraries/{itinerary_id}/party/members/{member_id}",
    response_model=ItineraryPartyResponse,
    summary="Remove a party member from this itinerary's party.",
)
async def detach_itinerary_party_member_endpoint(
    itinerary_id: uuid.UUID,
    member_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryPartyResponse:
    await _authorize_itinerary_client(session, user, itinerary_id)
    await detach_member_from_itinerary(
        session, itinerary_id=itinerary_id, member_id=member_id
    )
    return await list_itinerary_party_endpoint(itinerary_id, user=user, session=session)
