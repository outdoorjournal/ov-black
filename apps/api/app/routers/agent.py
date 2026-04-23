"""Agent session + turn HTTP surface (M001/S04 T05).

Three routes, all gated by the standard JWT middleware (no PUBLIC_PATHS
change — turns are always authenticated):

- ``POST /sessions``                     open or reuse a session for a client
- ``POST /sessions/{id}/turn``           SSE-stream one assistant turn
- ``GET  /sessions/{id}/turns``          replay every turn on a session

Authorization supports two principals per request: an **advisor** who
owns the client row (``clients.owner_id = user.sub``), or the **client
themself** (``clients.auth_user_id = user.sub``). The service enforces
this at the SQL boundary; on mismatch we collapse to 404 so the caller
cannot probe which session_ids exist (S01 D015 precedent).

No content-carrying logs in this module — all turn-level observability
lives in ``app.services.agent``. The only log event emitted here is the
startup-time ``agent.runtime.configured`` (wired in ``app.main``).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agent.bedrock import AgentRuntimeClient
from app.auth import AuthenticatedUser, require_user
from app.db import get_session, get_sessionmaker
from app.models import Profile, UserRole
from app.schemas.agent import (
    AgentTurnSummary,
    OpenSessionRequest,
    OpenSessionResponse,
    TurnRequest,
)
from app.services.agent import (
    ActorContext,
    SessionOutcome,
    TurnOutcome,
    list_turns,
    open_or_reuse_session,
    stream_turn,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("ov_black.routers.agent")

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Dependencies ───────────────────────────────────────────────────────────


def get_agent_runtime(request: Request) -> AgentRuntimeClient:
    """Return the process-wide AgentRuntimeClient stashed on app.state.

    Mirrors the ``get_inventory_registry`` seam from S02 — tests override
    this dependency to inject a ``MockAgentRuntimeClient`` with a scripted
    event trace.
    """
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None:  # pragma: no cover — guarded by lifespan startup
        raise HTTPException(
            status_code=503, detail="agent_runtime_not_configured"
        )
    return runtime


async def _actor_for_user(
    user: AuthenticatedUser,
    session: "AsyncSession",
) -> ActorContext:
    """Build an ActorContext by resolving the caller's role from public.profiles.

    - profile.role == advisor → ``actor_kind='advisor'``
    - profile.role == client  → ``actor_kind='user'`` (client principal)
    - missing profile or malformed sub → ``actor_kind='user'`` with
      ``user_id=None`` so the service's auth check collapses to 404/403
      without leaking row existence.
    """
    try:
        sub_uuid = uuid.UUID(user.sub)
    except ValueError:
        return ActorContext(user_id=None, actor_kind="user", actor_id=user.sub)

    result = await session.execute(select(Profile).where(Profile.id == sub_uuid))
    profile = result.scalar_one_or_none()
    if profile is not None and profile.role is UserRole.advisor:
        return ActorContext(
            user_id=sub_uuid, actor_kind="advisor", actor_id=user.sub
        )
    return ActorContext(user_id=sub_uuid, actor_kind="user", actor_id=user.sub)


# ── POST /sessions ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OpenSessionResponse,
    responses={
        201: {"description": "Session opened or reused — idempotent."},
        404: {"description": "No client with this id accessible to the caller."},
    },
    summary="Open or reuse an agent session for a client.",
)
async def create_session_endpoint(
    payload: OpenSessionRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> OpenSessionResponse:
    actor = await _actor_for_user(user, session)
    outcome, agent_session, itinerary_id = await open_or_reuse_session(
        get_sessionmaker(),
        actor=actor,
        client_id=payload.client_id,
        itinerary_id=payload.itinerary_id,
    )
    if outcome is not SessionOutcome.OK or agent_session is None:
        # Collapsed 404 shape (D015) — FORBIDDEN and CLIENT_NOT_FOUND both
        # land here so a caller cannot probe existence of a client_id.
        raise HTTPException(status_code=404, detail="client_not_found")
    return OpenSessionResponse(
        session_id=agent_session.id,
        agentcore_session_id=agent_session.agentcore_session_id,
        itinerary_id=itinerary_id,
    )


# ── POST /sessions/{id}/turn ────────────────────────────────────────────────


async def _load_session_with_client(
    session: "AsyncSession",
    session_id: uuid.UUID,
):
    """Return (agent_session, client) or (None, None) on miss."""
    from app.models import AgentSession, Client  # local import to avoid cycles

    row = (
        await session.execute(
            select(AgentSession, Client)
            .join(Client, Client.id == AgentSession.client_id)
            .where(AgentSession.id == session_id)
        )
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def _pre_stream_authz(
    actor: ActorContext,
    client_row,
) -> TurnOutcome:
    """Mirror the service's _authorize_actor check BEFORE opening the stream.

    We duplicate this one step to keep StreamingResponse from lighting up
    on a cross-tenant probe — the plan requires 404 (not an error SSE
    frame) in that case.
    """
    if actor.actor_kind == "advisor":
        if actor.user_id is None or client_row.owner_id != actor.user_id:
            return TurnOutcome.SESSION_NOT_YOURS
    elif actor.actor_kind == "user":
        if actor.user_id is None or client_row.auth_user_id != actor.user_id:
            return TurnOutcome.SESSION_NOT_YOURS
    return TurnOutcome.OK


@router.post(
    "/{session_id}/turn",
    responses={
        200: {
            "description": "SSE stream of first_token / delta / done frames.",
            "content": {"text/event-stream": {}},
        },
        404: {"description": "No session with this id accessible to the caller."},
        422: {"description": "Invalid content body (empty or > 8000 chars)."},
    },
    summary="Stream one assistant turn for an open agent session.",
)
async def turn_endpoint(
    session_id: uuid.UUID,
    payload: TurnRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> StreamingResponse:
    # Pre-stream auth/existence check — we must return a JSON 404 rather
    # than opening an SSE stream if the session doesn't belong to the
    # caller (D015 collapsed shape).
    actor = await _actor_for_user(user, session)
    agent_session, client_row = await _load_session_with_client(session, session_id)
    if agent_session is None or client_row is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if _pre_stream_authz(actor, client_row) is not TurnOutcome.OK:
        raise HTTPException(status_code=404, detail="session_not_found")

    runtime = get_agent_runtime(request)
    # Forward the raw Bearer token so the agent runtime can set
    # Authorization on its tool callbacks. Middleware has already
    # validated the JWT once; we simply strip the scheme here.
    raw_auth = request.headers.get("authorization", "")
    auth_bearer = (
        raw_auth.split(" ", 1)[1] if raw_auth.lower().startswith("bearer ") else ""
    )
    body_stream = stream_turn(
        get_sessionmaker(),
        runtime,
        actor=actor,
        session_id=session_id,
        content=payload.content,
        auth_bearer=auth_bearer,
    )
    return StreamingResponse(
        content=body_stream,
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# ── GET /sessions/{id}/turns ────────────────────────────────────────────────


@router.get(
    "/{session_id}/turns",
    response_model=list[AgentTurnSummary],
    responses={
        404: {"description": "No session with this id accessible to the caller."},
    },
    summary="List every turn on a session, ordered by turn_index ASC.",
)
async def list_turns_endpoint(
    session_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> list[AgentTurnSummary]:
    actor = await _actor_for_user(user, session)
    result = await list_turns(session, actor=actor, session_id=session_id)
    if isinstance(result, TurnOutcome):
        # Both SESSION_NOT_FOUND and SESSION_NOT_YOURS collapse to 404
        # (D015) — never 403 on cross-tenant, that would leak existence.
        raise HTTPException(status_code=404, detail="session_not_found")
    return [
        AgentTurnSummary(
            id=turn.id,
            turn_index=turn.turn_index,
            role=turn.role,
            content=turn.content,
            model=turn.model,
            latency_ms=turn.latency_ms,
            first_token_ms=turn.first_token_ms,
            retried=turn.retried,
            error_reason=turn.error_reason,
            created_at=turn.created_at,
        )
        for turn in result
    ]
