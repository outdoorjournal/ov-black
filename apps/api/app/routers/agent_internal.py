"""Backend-only routes the agent runtime calls with a per-session token.

These routes deliberately bypass the global Supabase JWT middleware
(:func:`app.auth.JWTAuthMiddleware`) — their paths live in ``PUBLIC_PATHS``
so the middleware skips them, and they validate an HS256 agent token
themselves via :func:`require_agent_token`. A Supabase client JWT presented
to these routes is rejected — that's the whole point of moving Dossier
and OSINT off ``/me/voodoo-doll``: the traveler must not be able to read
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

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.dossier import DossierDetail
from app.schemas.facts import (
    AgentContext,
    AgentRecordDossierInferenceRequest,
    AgentRecordProfileFactRequest,
    DossierFactDetail,
    OsintFactDetail,
    ProfileFactDetail,
)
from app.services.agent_token import (
    AgentTokenClaims,
    AgentTokenError,
    verify_agent_token,
)
from app.services.facts import (
    load_agent_context,
    record_agent_dossier_inference,
    record_agent_profile_fact,
)

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

    return AgentContext(
        client_id=ctx.client.id,
        client_full_name=ctx.client.full_name,
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
