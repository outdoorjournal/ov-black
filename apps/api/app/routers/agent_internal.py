"""Backend-only routes the agent runtime calls with a per-session token.

These routes deliberately bypass the global Supabase JWT middleware
(:func:`app.auth.JWTAuthMiddleware`) — their paths live in ``PUBLIC_PATHS``
so the middleware skips them, and they validate an HS256 agent token
themselves via :func:`require_agent_token`. A Supabase client JWT presented
to these routes is rejected — that's the whole point of moving Dossier
and OSINT off ``/me/dossier``: the traveler must not be able to read
their own private dossier or see what we've researched externally.

Three routes:

- ``GET  /agent/context``         — single payload of dossier + active facts
- ``POST /agent/profile/facts``   — record a fact the traveler **told** the agent
                                    (server stamps ``source_kind=traveler_told``)
- ``POST /agent/dossier/facts``   — record an internal **inference** the agent made
                                    (server stamps ``source_kind=agent_inferred``)

The two writes always pin ``source_kind`` server-side so a buggy or
compromised tool cannot escalate one tier into another.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AgentSession, Itinerary, PartyMemberActor
from app.schemas.dossier import DossierDetail
from app.schemas.facts import (
    AgentContext,
    AgentRecordDossierInferenceRequest,
    AgentRecordProfileFactRequest,
    DossierFactDetail,
    OsintFactDetail,
    ProfileFactDetail,
)
from app.schemas.party_members import PartyMemberCreate, PartyMemberDetail
from app.services.agent import trip_brief_for_itinerary
from app.services.agent_token import (
    AgentTokenClaims,
    AgentTokenError,
    verify_agent_token,
)
from app.services.facts import (
    _agent_recorded_by,
    load_agent_context,
    record_agent_dossier_inference,
    record_agent_profile_fact,
)
from app.services.party_members import create_party_member

logger = logging.getLogger("ov_black.routers.agent_internal")

router = APIRouter(prefix="/agent", tags=["agent-internal"])


def require_agent_token(
    authorization: str | None = Header(default=None),
) -> AgentTokenClaims:
    """FastAPI dependency that extracts + verifies the per-session agent token.

    Returns the decoded claims (session_id, client_id, agentcore_session_id)
    or raises 401 with a stable ``detail="agent_unauthorized"`` — verification
    reasons are deliberately collapsed so the route does not leak whether
    the failure was missing/expired/wrong-audience.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="agent_unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="agent_unauthorized")
    try:
        return verify_agent_token(token)
    except AgentTokenError as exc:
        logger.info("agent_internal.auth.rejected", extra={"reason": exc.reason})
        raise HTTPException(status_code=401, detail="agent_unauthorized") from exc


async def _resolve_session_fork_state(
    session: AsyncSession, session_id: uuid.UUID
) -> tuple[bool, str | None, bool]:
    """(is_alternative, baseline_title, reconcile_requested) for the session's pin (G3).

    Extracted so the agent-context route tests can stub it (the route's other DB
    read, ``load_agent_context``, is already stubbed the same way).
    """
    pinned_itinerary_id = (
        await session.execute(
            select(AgentSession.itinerary_id).where(AgentSession.id == session_id)
        )
    ).scalar_one_or_none()
    if pinned_itinerary_id is None:
        return (False, None, False)
    fork_row = (
        await session.execute(
            select(Itinerary.forked_from_id, Itinerary.reconcile_requested_at).where(
                Itinerary.id == pinned_itinerary_id
            )
        )
    ).first()
    if fork_row is None or fork_row.forked_from_id is None:
        return (False, None, False)
    baseline_title = (
        await session.execute(
            select(Itinerary.title).where(Itinerary.id == fork_row.forked_from_id)
        )
    ).scalar_one_or_none()
    return (True, baseline_title, fork_row.reconcile_requested_at is not None)


async def _resolve_session_trip_brief(session: AsyncSession, session_id: uuid.UUID) -> str | None:
    """The pinned itinerary's rendered brief + timing (0033) for this session.

    Extracted so the route tests can stub it, mirroring the fork-state read.
    """
    pinned_itinerary_id = (
        await session.execute(
            select(AgentSession.itinerary_id).where(AgentSession.id == session_id)
        )
    ).scalar_one_or_none()
    return await trip_brief_for_itinerary(session, pinned_itinerary_id)


@router.get(
    "/context",
    response_model=AgentContext,
    summary="Dossier + Profile + OSINT context for the agent (backend-only).",
)
async def get_agent_context_endpoint(
    claims: AgentTokenClaims = Depends(require_agent_token),
    session: AsyncSession = Depends(get_session),
) -> AgentContext:
    ctx = await load_agent_context(session, client_id=claims.client_id)
    if ctx is None:
        # The token is bound to a client_id; if that row doesn't exist
        # something is badly wrong — collapse to 404.
        raise HTTPException(status_code=404, detail="client_not_found")

    dossier_detail: DossierDetail | None = None
    if ctx.dossier is not None:
        dossier_detail = DossierDetail(
            id=ctx.dossier.id,
            contact_preference=ctx.dossier.contact_preference,
            children_ages=list(ctx.dossier.children_ages),
            travel_party_notes=ctx.dossier.travel_party_notes,
            estimated_net_worth_usd=ctx.dossier.estimated_net_worth_usd,
            created_at=ctx.dossier.created_at,
            updated_at=ctx.dossier.updated_at,
        )

    # Fork-awareness (G3): is the session pinned to a fork (alternative version)?
    is_alternative, baseline_title, reconcile_requested = await _resolve_session_fork_state(
        session, claims.session_id
    )

    # Trip brief (0033): the goal + timing the traveler set at intake, so the
    # agent grounds its suggestions in what they're planning.
    trip_brief = await _resolve_session_trip_brief(session, claims.session_id)

    return AgentContext(
        client_id=ctx.client.id,
        client_full_name=ctx.client.full_name,
        trip_brief=trip_brief,
        is_alternative=is_alternative,
        baseline_title=baseline_title,
        reconcile_requested=reconcile_requested,
        dossier=dossier_detail,
        dossier_facts=[
            DossierFactDetail.model_validate(f, from_attributes=True) for f in ctx.dossier_facts
        ],
        profile_facts=[
            ProfileFactDetail.model_validate(f, from_attributes=True) for f in ctx.profile_facts
        ],
        osint_facts=[
            OsintFactDetail.model_validate(f, from_attributes=True) for f in ctx.osint_facts
        ],
        party_members=[
            PartyMemberDetail.model_validate(m, from_attributes=True) for m in ctx.party_members
        ],
    )


@router.post(
    "/profile/facts",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileFactDetail,
    summary="Record a fact the traveler told the agent (source_kind=traveler_told).",
)
async def record_profile_fact_endpoint(
    payload: AgentRecordProfileFactRequest,
    claims: AgentTokenClaims = Depends(require_agent_token),
    session: AsyncSession = Depends(get_session),
) -> ProfileFactDetail:
    fact = await record_agent_profile_fact(
        session,
        client_id=claims.client_id,
        agentcore_session_id=claims.agentcore_session_id,
        session_id=claims.session_id,
        kind=payload.kind,
        text=payload.text,
        source_turn_id=payload.source_turn_id,
    )
    return ProfileFactDetail.model_validate(fact, from_attributes=True)


@router.post(
    "/dossier/facts",
    status_code=status.HTTP_201_CREATED,
    response_model=DossierFactDetail,
    summary="Record a private agent inference (source_kind=agent_inferred).",
)
async def record_dossier_inference_endpoint(
    payload: AgentRecordDossierInferenceRequest,
    claims: AgentTokenClaims = Depends(require_agent_token),
    session: AsyncSession = Depends(get_session),
) -> DossierFactDetail:
    fact = await record_agent_dossier_inference(
        session,
        client_id=claims.client_id,
        agentcore_session_id=claims.agentcore_session_id,
        session_id=claims.session_id,
        kind=payload.kind,
        text=payload.text,
        source_turn_id=payload.source_turn_id,
    )
    return DossierFactDetail.model_validate(fact, from_attributes=True)


@router.post(
    "/party-members",
    status_code=status.HTTP_201_CREATED,
    response_model=PartyMemberDetail,
    summary="Record a party member the traveler mentioned (actor=agent).",
)
async def record_party_member_endpoint(
    payload: PartyMemberCreate,
    claims: AgentTokenClaims = Depends(require_agent_token),
    session: AsyncSession = Depends(get_session),
) -> PartyMemberDetail:
    """Save a durable household member the traveler named in conversation.

    ``actor`` is fixed to ``agent`` server-side (the body cannot override it);
    ``recorded_by`` is the deterministic per-session stamp so the command
    center can group "who the agent added during session X". Party data is
    SHARED — the agent may confirm it with the traveler, unlike Dossier/OSINT.
    """
    member = await create_party_member(
        session,
        client_id=claims.client_id,
        payload=payload,
        actor=PartyMemberActor.agent,
        recorded_by=_agent_recorded_by(claims.agentcore_session_id),
    )
    return PartyMemberDetail.model_validate(member, from_attributes=True)
