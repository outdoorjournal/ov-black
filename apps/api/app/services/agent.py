"""Agent turn orchestration — session open/reuse + SSE stream + retry envelope.

This service ties together three moving parts for one conversational turn:

1. **Postgres**: two short-lived transactions (user-write before the stream,
   assistant-write after) instead of one transaction spanning the network
   call. Holding a connection open for the length of an LLM stream would
   pin a pool slot for seconds and starve other requests under any load.
2. **Bedrock AgentCore**: a single ``invoke_stream`` per attempt with a
   retry envelope around the *first call only* — once we have emitted any
   SSE byte downstream, we never retry (the client is already consuming a
   stream; retrying would produce a visible stutter or duplicate content).
3. **SSE framing**: ``first_token``, ``delta``, ``done``, and an ``error``
   fallback frame, plus any unknown frame (e.g. S07's ``card`` frame for
   OV experience proposals) forwarded verbatim from the runtime. All
   frames flow from this module as raw ``bytes`` so the router layer is
   a thin conduit.

**Redaction discipline (S04 slice verification, R-PRIVACY):** the content
variables ``content`` / ``user_text`` / ``assistant_text`` / ``prompt`` /
``context`` MUST NEVER appear in any log call. Only ``session_id``,
``turn_index``, ``turn_id``, timings, counts, and stable ``reason``
strings are allowed in log ``extra`` payloads. The grep in this task's
verification command enforces this rule statically over this module.
"""

from __future__ import annotations

import enum
import json
import logging
import random
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import anyio
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bedrock import AgentRuntimeClient, AgentRuntimeError
from app.agent.prompt import build_system_prompt
from app.agent.traveler_context import assemble_traveler_context, format_trip_brief
from app.config import Settings, get_settings
from app.models import (
    AgentSession,
    AgentTurn,
    Client,
    Dossier,
    ForkStatus,
    Itinerary,
    Message,
    NodeStatus,
    NodeType,
    SessionAudience,
    Thread,
    ThreadActorKind,
    ThreadKind,
    TurnRole,
)
from app.observability import emit_metric
from app.services import fork as fork_service
from app.services import itineraries as itineraries_service
from app.services.agent_token import AgentTokenError, mint_agent_token
from app.services.display_status import DisplayStatus, display_status_expr
from app.services.facts import load_agent_context
from app.services.graph_digest import graph_digest_for_itinerary

logger = logging.getLogger("ov_black.agent.service")


# ── Outcome enums ──────────────────────────────────────────────────────────


class SessionOutcome(str, enum.Enum):
    """Terminal states of ``open_or_reuse_session``."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    FORBIDDEN = "forbidden"


class TurnOutcome(str, enum.Enum):
    """Terminal states of a turn attempt.

    These are not returned from ``stream_turn`` — they drive the pre-stream
    auth / validation branch that short-circuits before any bytes go out.
    """

    OK = "ok"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_NOT_YOURS = "session_not_yours"
    INVALID_INPUT = "invalid_input"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


# ── Actor + result shapes ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Request-scoped principal for session + turn attribution.

    ``user_id`` is the Supabase ``auth.users`` UUID when a human user is on
    the other side of the request. ``actor_kind`` distinguishes between
    'user' (the client), 'advisor' (the ops-side human), and 'agent' (the
    LLM itself writing a turn). ``actor_id`` is a stable string — the
    user's sub for humans, the ``agentcore_session_id`` for agent writes.
    """

    user_id: uuid.UUID | None
    actor_kind: Literal["user", "advisor", "agent"]
    actor_id: str


# Sentinel frame the router inspects before committing the upstream-ok
# path. The exact bytes are part of the SSE contract with the browser.
_FALLBACK_FRAME: bytes = b'data: {"type":"error","reason":"upstream_unavailable"}\n\n'


def _sse_encode(event: dict[str, Any]) -> bytes:
    """Encode one frame as ``data: <json>\\n\\n``."""
    return b"data: " + json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n\n"


def _arn_tail(arn: str) -> str | None:
    """Return the last path segment of the AgentCore runtime ARN for logs.

    Full ARNs are redaction-sensitive — we log the trailing agent identifier
    only (S04 redaction constraint #2). Empty string ARN returns ``None``.
    """
    if not arn:
        return None
    return arn.rsplit("/", 1)[-1][-8:] or None


def _derive_session_title(content: str, *, max_length: int = 60) -> str:
    """A short session label from the first user message (M006/PS2).

    Collapse whitespace, then truncate on a word boundary near ``max_length``
    with an ellipsis when cut. Never logged — it's derived from user content.
    """
    stripped = " ".join(content.split()).strip()
    if len(stripped) <= max_length:
        return stripped
    head = stripped[:max_length].rsplit(" ", 1)[0].rstrip()
    return f"{head or stripped[:max_length].rstrip()}…"


# ── open_or_reuse_session ──────────────────────────────────────────────────


async def _enforce_client_access(
    session: AsyncSession,
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
) -> SessionOutcome:
    """Return OK / CLIENT_NOT_FOUND / FORBIDDEN for (actor, client_id).

    Enforcement rules mirror the S02/S03 posture:
      - advisor: must own the client (clients.owner_id == actor.user_id).
      - user: must be the signed-in client (clients.auth_user_id == actor.user_id).
      - agent: inherits the session it's writing on behalf of — caller
        must have already verified it; here we just check the client row
        exists.
    """
    client = (
        await session.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        return SessionOutcome.CLIENT_NOT_FOUND
    if actor.actor_kind == "advisor":
        if actor.user_id is None or client.owner_id != actor.user_id:
            return SessionOutcome.FORBIDDEN
    elif actor.actor_kind == "user" and (
        actor.user_id is None or client.auth_user_id != actor.user_id
    ):
        return SessionOutcome.FORBIDDEN
    # actor_kind == 'agent' is internal — no additional gate here.
    return SessionOutcome.OK


async def _jit_backfill_client_auth_user_id(
    session: AsyncSession,
    *,
    client: Client,
    user_id: uuid.UUID,
) -> bool:
    """Best-effort JIT populate ``clients.auth_user_id`` on first POST /sessions.

    S03 creates clients with ``auth_user_id IS NULL``; after the client
    signs in via their magic link they have an ``auth.users`` row but the
    link back is not established anywhere. This helper closes that gap
    *only* when the caller is the client themself and the Supabase
    ``auth.users`` email for their JWT sub matches the clients row email
    case-insensitively. On any SQL error (including a permission denial on
    ``auth.users``) the helper fails closed — leaves ``auth_user_id`` NULL
    and returns ``False`` so the caller collapses to the FORBIDDEN / 404
    branch rather than crashing the request. Returns ``True`` when the
    backfill succeeded and the in-memory ``client`` row was mutated.

    No email string is ever logged or attached to this function's return.
    """
    try:
        result = await session.execute(
            sql_text("SELECT email FROM auth.users WHERE id = :user_id"),
            {"user_id": str(user_id)},
        )
        row = result.first()
    except SQLAlchemyError:
        return False

    if row is None:
        return False
    auth_email = row[0]
    if not auth_email or not client.email:
        return False
    if auth_email.strip().lower() != client.email.strip().lower():
        return False

    accepted_at = datetime.now(UTC)
    try:
        await session.execute(
            update(Client)
            .where(Client.id == client.id, Client.auth_user_id.is_(None))
            .values(auth_user_id=user_id, accepted_at=accepted_at)
        )
        # Same-transaction profiles upsert: keep the auth grid self-consistent
        # by ensuring a profiles row with role='client' exists for this user.
        # ON CONFLICT DO NOTHING makes this a no-op when a row already exists
        # (even if it's an advisor row — we MUST NOT downgrade an existing
        # profile). If this INSERT fails the whole transaction rolls back so
        # clients.auth_user_id stays NULL and the caller collapses to FORBIDDEN.
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
        return False

    # Keep the in-memory row in sync so the subsequent access check sees it.
    client.auth_user_id = user_id
    client.accepted_at = accepted_at
    return True


async def dismiss_onboarding(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
) -> SessionOutcome:
    """Mark the calling client's onboarding "dismissed".

    Side effects (one transaction):
      - Sets ``ended_at = NOW()`` on every active session for the client.
      - If no session row has ever existed for the client, inserts a
        marker session (no opener) with ``ended_at = NOW()`` so the
        ``has_prior_session`` gate flips to true on the next page load.

    Idempotent: calling twice is harmless. Returns ``OK`` on success,
    ``CLIENT_NOT_FOUND`` / ``FORBIDDEN`` to mirror the access posture of
    :func:`open_or_reuse_session`.
    """
    async with session_factory() as session:
        client = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        if client is None:
            return SessionOutcome.CLIENT_NOT_FOUND
        if actor.actor_kind == "advisor":
            if actor.user_id is None or client.owner_id != actor.user_id:
                return SessionOutcome.FORBIDDEN
        elif actor.actor_kind == "user" and (
            actor.user_id is None or client.auth_user_id != actor.user_id
        ):
            return SessionOutcome.FORBIDDEN

        now = datetime.now(UTC)
        result = await session.execute(
            update(AgentSession)
            .where(
                AgentSession.client_id == client_id,
                AgentSession.ended_at.is_(None),
            )
            .values(ended_at=now)
        )
        ended_count = int(cast("CursorResult[Any]", result).rowcount or 0)

        if ended_count == 0:
            any_existing = (
                await session.execute(
                    select(AgentSession.id).where(AgentSession.client_id == client_id).limit(1)
                )
            ).scalar_one_or_none()
            if any_existing is None:
                marker = AgentSession(
                    client_id=client_id,
                    agentcore_session_id=str(uuid.uuid4()),
                    ended_at=now,
                )
                session.add(marker)

        await session.commit()

    logger.info(
        "agent.session.dismiss",
        extra={
            "client_id": str(client_id),
            "ended_count": ended_count,
        },
    )
    return SessionOutcome.OK


async def open_or_reuse_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
    itinerary_id: uuid.UUID | None = None,
    seeded_opener: str | None = None,
    audience: SessionAudience = SessionAudience.traveler,
    force_new: bool = False,
) -> tuple[SessionOutcome, AgentSession | None, uuid.UUID | None]:
    """Open — or reuse the most-recent live — AgentSession for a scope.

    Reuse honours SCOPE (M006/PS2): the newest LIVE session (``ended_at IS
    NULL`` and ``archived_at IS NULL``) for the exact
    ``(client_id, audience, itinerary_id)`` is returned; else INSERT one with a
    fresh ``agentcore_session_id``. A session's scope is fixed at creation —
    it is **never re-pinned** — so opening a different itinerary opens a
    different session (this is the fix for the old single-re-pinned-session
    bug). ``force_new`` skips reuse entirely for the explicit "＋ new session"
    path. Caller cannot distinguish reuse from create from the HTTP surface.

    ``itinerary_id``:
      - **Omitted / None**: basecamp scope (unpinned) — onboarding / Q&A.
      - **Provided**: itinerary scope. The itinerary must belong to
        ``client_id`` or the call is rejected with ``FORBIDDEN``.
    """
    async with session_factory() as session:
        client = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        if client is None:
            return SessionOutcome.CLIENT_NOT_FOUND, None, None

        # JIT-backfill the client↔auth.users link on the first POST /sessions
        # made by the client themself.
        backfilled = False
        if actor.actor_kind == "user" and actor.user_id is not None and client.auth_user_id is None:
            backfilled = await _jit_backfill_client_auth_user_id(
                session, client=client, user_id=actor.user_id
            )

        # Access check against the (possibly-updated) client row.
        if actor.actor_kind == "advisor":
            if actor.user_id is None or client.owner_id != actor.user_id:
                return SessionOutcome.FORBIDDEN, None, None
        elif actor.actor_kind == "user" and (
            actor.user_id is None or client.auth_user_id != actor.user_id
        ):
            return SessionOutcome.FORBIDDEN, None, None
        # actor_kind == 'agent' is internal — no additional gate here.

        # A traveler may only ever open the client-facing thread; the private
        # advisor workspace is staff-only. Collapsed to FORBIDDEN → 404 so a
        # traveler can't even probe that an advisor audience exists.
        if audience == SessionAudience.advisor and actor.actor_kind == "user":
            return SessionOutcome.FORBIDDEN, None, None

        # If the caller is pinning the session, verify the itinerary
        # actually belongs to this client. Hides existence of foreign
        # itineraries behind the standard FORBIDDEN outcome.
        if itinerary_id is not None:
            owner_cid = (
                await session.execute(
                    select(Itinerary.client_id).where(Itinerary.id == itinerary_id)
                )
            ).scalar_one_or_none()
            if owner_cid is None or owner_cid != client_id:
                return SessionOutcome.FORBIDDEN, None, None

        # Reuse the most-recent LIVE session for this EXACT scope — never
        # re-pinned. `force_new` opts out for the "＋ new session" path.
        existing: AgentSession | None = None
        if not force_new:
            scope_match = (
                AgentSession.itinerary_id.is_(None)
                if itinerary_id is None
                else AgentSession.itinerary_id == itinerary_id
            )
            existing = (
                (
                    await session.execute(
                        select(AgentSession)
                        .where(
                            AgentSession.client_id == client_id,
                            AgentSession.audience == audience,
                            scope_match,
                            AgentSession.ended_at.is_(None),
                            AgentSession.archived_at.is_(None),
                        )
                        .order_by(AgentSession.started_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
        if existing is not None:
            if backfilled:
                logger.info(
                    "agent.auth.client_backfilled",
                    extra={
                        "session_id": str(existing.id),
                        "client_id": str(client_id),
                        "user_id": str(actor.user_id),
                    },
                )
            logger.info(
                "agent.session.reuse",
                extra={
                    "session_id": str(existing.id),
                    "client_id": str(client_id),
                    "itinerary_pinned": existing.itinerary_id is not None,
                },
            )
            return SessionOutcome.OK, existing, existing.itinerary_id

        new = AgentSession(
            client_id=client_id,
            agentcore_session_id=str(uuid.uuid4()),
            itinerary_id=itinerary_id,
            seeded_opener=seeded_opener,
            audience=audience,
        )
        session.add(new)
        await session.commit()
        await session.refresh(new)

        # When basecamp pre-shows the opener, persist it as turn_index=0 so the
        # opener lives in the conversation history (visible on reload) and the
        # agent sees it via prior_turns instead of echoing it from a directive.
        if seeded_opener:
            opener_turn = AgentTurn(
                session_id=new.id,
                turn_index=0,
                role=TurnRole.assistant,
                content=seeded_opener,
                actor_kind="agent",
                actor_id=new.agentcore_session_id,
                retried=0,
            )
            session.add(opener_turn)
            await session.commit()
        if backfilled:
            logger.info(
                "agent.auth.client_backfilled",
                extra={
                    "session_id": str(new.id),
                    "client_id": str(client_id),
                    "user_id": str(actor.user_id),
                },
            )
        logger.info(
            "agent.session.open",
            extra={
                "session_id": str(new.id),
                "client_id": str(client_id),
                "itinerary_pinned": new.itinerary_id is not None,
            },
        )
        return SessionOutcome.OK, new, new.itinerary_id


# ── list_sessions / patch_session (M006/PS2) ───────────────────────────────


async def list_sessions(
    session: AsyncSession,
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
    itinerary_id: uuid.UUID | None = None,
    audience: SessionAudience = SessionAudience.traveler,
) -> tuple[SessionOutcome, list[AgentSession]]:
    """The non-archived sessions for a scope, newest first (M006/PS2).

    Scope = ``(client_id, audience, itinerary_id)`` — the same key reuse
    honours. Access mirrors :func:`open_or_reuse_session`: the client must be
    accessible to the actor, and a traveler may never list the private advisor
    audience (collapsed to FORBIDDEN → 404 so its existence stays hidden).
    """
    access = await _enforce_client_access(session, actor=actor, client_id=client_id)
    if access is not SessionOutcome.OK:
        return access, []
    if audience == SessionAudience.advisor and actor.actor_kind == "user":
        return SessionOutcome.FORBIDDEN, []

    scope_match = (
        AgentSession.itinerary_id.is_(None)
        if itinerary_id is None
        else AgentSession.itinerary_id == itinerary_id
    )
    rows = (
        (
            await session.execute(
                select(AgentSession)
                .where(
                    AgentSession.client_id == client_id,
                    AgentSession.audience == audience,
                    scope_match,
                    AgentSession.archived_at.is_(None),
                )
                .order_by(AgentSession.started_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return SessionOutcome.OK, list(rows)


async def patch_session(
    session: AsyncSession,
    *,
    actor: ActorContext,
    session_id: uuid.UUID,
    title: str | None = None,
    archived: bool | None = None,
) -> tuple[SessionOutcome, AgentSession | None]:
    """Rename and/or (un)archive a session (M006/PS2).

    Access is checked against the session's owning client. A traveler may never
    touch a private advisor-audience session (collapsed to FORBIDDEN → 404).
    ``title``/``archived`` are each optional — omitted means "leave as is".
    """
    row = (
        await session.execute(
            select(AgentSession, Client)
            .join(Client, Client.id == AgentSession.client_id)
            .where(AgentSession.id == session_id)
        )
    ).first()
    if row is None:
        # Collapse a missing session to CLIENT_NOT_FOUND → 404 (existence-hiding).
        return SessionOutcome.CLIENT_NOT_FOUND, None
    agent_session, client = row

    if actor.actor_kind == "advisor":
        if actor.user_id is None or client.owner_id != actor.user_id:
            return SessionOutcome.FORBIDDEN, None
    elif actor.actor_kind == "user" and (
        actor.user_id is None or client.auth_user_id != actor.user_id
    ):
        return SessionOutcome.FORBIDDEN, None
    if agent_session.audience == SessionAudience.advisor and actor.actor_kind == "user":
        return SessionOutcome.FORBIDDEN, None

    if title is not None:
        agent_session.title = title.strip() or None
    if archived is not None:
        agent_session.archived_at = datetime.now(UTC) if archived else None
    await session.commit()
    await session.refresh(agent_session)
    return SessionOutcome.OK, agent_session


# ── list_turns ─────────────────────────────────────────────────────────────


async def list_turns(
    session: AsyncSession,
    *,
    actor: ActorContext,
    session_id: uuid.UUID,
    limit: int | None = None,
    before_index: int | None = None,
) -> list[AgentTurn] | TurnOutcome:
    """Return a session's turns ordered by turn_index ASC.

    No params → every turn (the pre-Wave-F behavior, kept for the chat replay
    and the ovb SDK). With ``limit`` the MOST RECENT ``limit`` turns (still
    returned ascending); ``before_index`` windows to turns strictly below that
    index — ``turn_index`` is a dense per-session int with a unique
    constraint, so it doubles as the page cursor with no opaque token.

    Returns a ``TurnOutcome`` on failure so the router layer can map to
    404 / 403 without leaking DB internals.
    """
    agent_session = (
        await session.execute(select(AgentSession).where(AgentSession.id == session_id))
    ).scalar_one_or_none()
    if agent_session is None:
        return TurnOutcome.SESSION_NOT_FOUND

    access = await _enforce_client_access(session, actor=actor, client_id=agent_session.client_id)
    if access is SessionOutcome.CLIENT_NOT_FOUND:
        return TurnOutcome.SESSION_NOT_FOUND
    if access is SessionOutcome.FORBIDDEN:
        return TurnOutcome.SESSION_NOT_YOURS
    # A private advisor session is never readable by a traveler, even one who
    # owns the client. Collapsed to 404 (existence-hiding) like every other gate.
    if agent_session.audience == SessionAudience.advisor and actor.actor_kind != "advisor":
        return TurnOutcome.SESSION_NOT_FOUND

    stmt = select(AgentTurn).where(AgentTurn.session_id == session_id)
    if before_index is not None:
        stmt = stmt.where(AgentTurn.turn_index < before_index)
    if limit is not None:
        # Newest `limit` of the window, flipped back to ascending for callers.
        page = (
            (
                await session.execute(
                    stmt.order_by(AgentTurn.turn_index.desc()).limit(max(1, min(limit, 500)))
                )
            )
            .scalars()
            .all()
        )
        return sorted(page, key=lambda t: t.turn_index)
    rows = (await session.execute(stmt.order_by(AgentTurn.turn_index))).scalars().all()
    return list(rows)


# ── stream_turn ────────────────────────────────────────────────────────────


async def _fork_baseline_title(session: AsyncSession, itinerary_id: uuid.UUID | None) -> str | None:
    """The baseline title when ``itinerary_id`` is a fork, else None (G3).

    A non-None return (even an empty string) means the pinned itinerary is an
    alternative version, so the prompt frames it as such. None means it is a
    normal itinerary (or unpinned) and no fork framing is added.
    """
    if itinerary_id is None:
        return None
    forked_from_id = (
        await session.execute(select(Itinerary.forked_from_id).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if forked_from_id is None:
        return None
    title = (
        await session.execute(select(Itinerary.title).where(Itinerary.id == forked_from_id))
    ).scalar_one_or_none()
    return title or ""


async def trip_brief_for_itinerary(
    session: AsyncSession, itinerary_id: uuid.UUID | None
) -> str | None:
    """Render the pinned itinerary's first-class brief + timing (0033) for the
    prompt, or None when there's nothing to say.

    A fork carries no brief of its own (the intake gates baselines only), so when
    the pin is a fork with an empty brief we inherit the baseline's — the
    alternative version is still about the same trip.
    """
    if itinerary_id is None:
        return None
    row = (
        await session.execute(
            select(
                Itinerary.brief,
                Itinerary.timing_kind,
                Itinerary.date_start,
                Itinerary.date_end,
                Itinerary.duration_nights,
                Itinerary.timing_note,
                Itinerary.forked_from_id,
            ).where(Itinerary.id == itinerary_id)
        )
    ).first()
    if row is None:
        return None
    brief, timing_kind, date_start, date_end, duration_nights, timing_note, forked_from_id = row

    # Fork with no brief of its own → fall back to the baseline's intent.
    if (brief is None or not brief.strip()) and forked_from_id is not None:
        base = (
            await session.execute(
                select(
                    Itinerary.brief,
                    Itinerary.timing_kind,
                    Itinerary.date_start,
                    Itinerary.date_end,
                    Itinerary.duration_nights,
                    Itinerary.timing_note,
                ).where(Itinerary.id == forked_from_id)
            )
        ).first()
        if base is not None:
            brief, timing_kind, date_start, date_end, duration_nights, timing_note = base

    return format_trip_brief(
        brief=brief,
        timing_kind=timing_kind.value if timing_kind is not None else None,
        date_start=date_start.isoformat() if date_start is not None else None,
        date_end=date_end.isoformat() if date_end is not None else None,
        duration_nights=duration_nights,
        timing_note=timing_note,
    )


async def _detect_mode(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID | None,
    client_id: uuid.UUID,
) -> str:
    """Classify the turn as ``onboarding``, ``planning``, or ``qa``.

    Rules (display status is derived — see :mod:`app.services.display_status`):

    - **planning**: session is pinned to a fork (a working copy is always
      planning), or to a trunk that hasn't fully bucketed ``approved``.
    - **qa**: session is pinned to an ``approved`` trunk, OR session is
      unpinned and the client already has ≥1 ``approved`` trunk.
    - **onboarding**: session is unpinned and the client has no
      approved trunks yet.

    One SQL round-trip in the pinned case; one in the unpinned case.
    Always returns a string — never raises — so a DB hiccup can't break
    a turn; worst case we default to ``onboarding`` and let the agent
    reorient.
    """
    try:
        if itinerary_id is not None:
            row = (
                await session.execute(
                    select(Itinerary.forked_from_id, display_status_expr()).where(
                        Itinerary.id == itinerary_id
                    )
                )
            ).one_or_none()
            if row is None:
                return "planning"
            forked_from_id, bucket = row
            if forked_from_id is None and bucket == DisplayStatus.approved.value:
                return "qa"
            return "planning"

        any_approved = (
            await session.execute(
                select(func.count())
                .select_from(Itinerary)
                .where(
                    Itinerary.client_id == client_id,
                    Itinerary.forked_from_id.is_(None),
                    display_status_expr() == DisplayStatus.approved.value,
                )
            )
        ).scalar_one_or_none()
        return "qa" if any_approved else "onboarding"
    except (SQLAlchemyError, AssertionError):
        # Tests with fake-factory session objects may not model this
        # exact query; fall back to the safe default rather than crash
        # the turn. A production DB hiccup collapses here too.
        return "onboarding"


async def _load_prior_turns(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Fetch the last ``limit`` user/assistant turns for conversational context.

    Excludes ``system``/``tool``/``error`` roles — those are not part of
    the model-visible history. Returns oldest-first so the runtime can
    prepend the current user message without a reversal.
    """
    try:
        rows = (
            await session.execute(
                select(AgentTurn.role, AgentTurn.content)
                .where(
                    AgentTurn.session_id == session_id,
                    AgentTurn.role.in_((TurnRole.user, TurnRole.assistant)),
                    AgentTurn.content != "",
                )
                .order_by(AgentTurn.turn_index.desc())
                .limit(limit)
            )
        ).all()
    except (SQLAlchemyError, AssertionError):
        # Fake-factory tests may not model this query; conversation history
        # is best-effort — a miss just means the model starts fresh.
        return []
    return [
        {"role": r.role.value if hasattr(r.role, "value") else str(r.role), "content": r.content}
        for r in reversed(rows)
    ]


async def _load_session_context(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> tuple[AgentSession, Client, Dossier] | None:
    """Join agent_session → client → dossier in one round trip.

    Profile + OSINT + dossier facts are loaded separately by
    :func:`app.services.facts.load_agent_context` and merged in by the
    caller (so we don't bloat this single join with three correlated
    sub-selects).
    """
    row = (
        await session.execute(
            select(AgentSession, Client, Dossier)
            .join(Client, Client.id == AgentSession.client_id)
            .join(Dossier, Dossier.client_id == Client.id)
            .where(AgentSession.id == session_id)
        )
    ).first()
    if row is None:
        return None
    agent_session, client, dossier = row
    return agent_session, client, dossier


async def _next_turn_index(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> int:
    """Compute ``max(turn_index) + 1`` under a row lock to serialize writers.

    Postgres ``FOR UPDATE`` on an aggregate is not meaningful, so we lock
    the parent ``agent_sessions`` row instead. A second concurrent writer
    will block here until the first commits, at which point its MAX query
    sees the newly-inserted user turn. Unique(session_id, turn_index)
    remains the belt in case any caller bypasses this helper.
    """
    await session.execute(
        select(AgentSession.id).where(AgentSession.id == session_id).with_for_update()
    )
    current_max = (
        await session.execute(
            select(func.max(AgentTurn.turn_index)).where(AgentTurn.session_id == session_id)
        )
    ).scalar_one()
    return 0 if current_max is None else int(current_max) + 1


async def _ensure_itinerary_for_client(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> uuid.UUID:
    """Return the itinerary id for ``client_id`` — one per client.

    S07 resolves the client's itinerary lazily at card-proposal time:
    agent_sessions has no itinerary_id column, and we do not want a
    long-lived column coupling sessions to itineraries. Idempotent:
    SELECT first, INSERT only if absent.
    """
    existing = (
        await session.execute(select(Itinerary.id).where(Itinerary.client_id == client_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    itinerary = Itinerary(
        client_id=client_id,
        created_by=actor_user_id,
        title="Concierge draft",
    )
    session.add(itinerary)
    await session.commit()
    await session.refresh(itinerary)
    return itinerary.id


# ── Agent write queue (S08 T03) ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class QueuedMutation:
    """One agent-initiated write stalled behind an active advisor lock.

    Shape is intentionally flat: the drain path opens a fresh DB session
    per entry and calls ``add_node`` with the stored payload, so nothing
    in here references a live session or transaction. ``actor`` carries
    the original AGENT ActorContext so the replayed history row still
    attributes provenance correctly.
    """

    itinerary_id: uuid.UUID
    session_id: uuid.UUID
    op: str  # M001 scope: only 'add_node' ever lands here.
    payload: dict[str, Any]
    actor: itineraries_service.ActorContext
    queued_at: datetime


# Module-level singleton keyed on itinerary_id. D008 accepts in-memory-only
# durability for M001 — advisor sessions span a single API process, and the
# window between ``acquire_lock`` and ``release_lock`` is bounded (minutes).
# A follow-up milestone can back this with a ``pending_agent_writes`` table
# for cross-process durability without changing the call signatures below.
_agent_write_queue: dict[uuid.UUID, list[QueuedMutation]] = {}


def queue_depth(itinerary_id: uuid.UUID) -> int:
    """Return the number of queued agent mutations for ``itinerary_id``.

    Test-only helper — production paths never need to inspect depth.
    Returns 0 for any itinerary with no entries (including ones that were
    fully drained; ``drain_queue`` deletes the key on exit).
    """
    return len(_agent_write_queue.get(itinerary_id, ()))


async def drain_queue(
    session_factory: async_sessionmaker[AsyncSession],
    itinerary_id: uuid.UUID,
) -> int:
    """Replay every queued mutation for ``itinerary_id`` in FIFO order.

    Called from the release-lock route handler after ``locked_by`` has been
    cleared, so the natural write-gate pass now admits agent writes.
    Each entry gets a fresh session — isolating one replay's rollback
    from the next. Per-entry failures are logged and dropped so a single
    bad payload never blocks the rest of the queue or the release path.

    Returns the count of successfully-replayed entries.
    """
    pending = _agent_write_queue.pop(itinerary_id, None)
    if not pending:
        return 0

    replayed = 0
    for entry in pending:
        try:
            async with session_factory() as db:
                result = await itineraries_service.add_node(
                    db,
                    entry.actor,
                    itinerary_id=entry.itinerary_id,
                    **entry.payload,
                )
            if isinstance(result, itineraries_service.ItineraryError):
                logger.warning(
                    "itinerary.agent_write_replay_failed",
                    extra={
                        "session_id": str(entry.session_id),
                        "itinerary_id": str(entry.itinerary_id),
                        "reason": result.outcome.value,
                    },
                )
                continue
            logger.info(
                "itinerary.agent_write_replayed",
                extra={
                    "session_id": str(entry.session_id),
                    "itinerary_id": str(entry.itinerary_id),
                    "op": entry.op,
                    "node_id": str(result.id),
                },
            )
            replayed += 1
        except Exception as exc:  # noqa: BLE001 — per-entry isolation
            logger.warning(
                "itinerary.agent_write_replay_failed",
                extra={
                    "session_id": str(entry.session_id),
                    "itinerary_id": str(entry.itinerary_id),
                    "reason": exc.__class__.__name__,
                },
            )
            continue
    return replayed


async def _resolve_card_itinerary(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    session_id: uuid.UUID,
    agentcore_session_id: str,
) -> uuid.UUID:
    """Where an agent-proposed card may land: a working fork, never a trunk.

    The trunk guard rejects AGENT content writes on an official trunk
    (content reaches a trunk only via publish/reconcile), but web pins chat
    sessions to the page's itinerary — the trunk when the traveler views
    Official. Resolve trunk → the session client's open fork of it, lazily
    forking (``created_by`` = the traveler's auth user, so the web/CLI
    viewer-fork resolution finds the same working copy). If the pinned
    itinerary is already a fork — or resolution fails — return the input and
    let ``add_node`` surface the outcome.
    """
    row = (
        await session.execute(select(Itinerary.forked_from_id).where(Itinerary.id == itinerary_id))
    ).one_or_none()
    if row is None or row[0] is not None:
        return itinerary_id  # missing (404s downstream) or already a fork

    auth_user_id = (
        await session.execute(
            select(Client.auth_user_id)
            .join(AgentSession, AgentSession.client_id == Client.id)
            .where(AgentSession.id == session_id)
        )
    ).scalar_one_or_none()
    created_by_match = (
        Itinerary.created_by == auth_user_id
        if auth_user_id is not None
        else Itinerary.created_by.is_(None)
    )
    fork_id = (
        await session.execute(
            select(Itinerary.id)
            .where(
                Itinerary.forked_from_id == itinerary_id,
                Itinerary.fork_status == ForkStatus.open,
                created_by_match,
            )
            .order_by(Itinerary.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if fork_id is not None:
        return fork_id

    fork_actor = itineraries_service.ActorContext(
        user_id=auth_user_id,
        kind=itineraries_service.ActorKind.AGENT,
        actor_id=agentcore_session_id,
    )
    fork = await fork_service.fork_itinerary(session, fork_actor, itinerary_id=itinerary_id)
    if isinstance(fork, itineraries_service.ItineraryError):
        logger.warning(
            "agent.card.fork_failed",
            extra={
                "session_id": str(session_id),
                "itinerary_id": str(itinerary_id),
                "reason": fork.outcome.value,
            },
        )
        return itinerary_id
    logger.info(
        "agent.card.fork_created",
        extra={
            "session_id": str(session_id),
            "itinerary_id": str(itinerary_id),
            "fork_id": str(fork.id),
        },
    )
    return fork.id


async def _persist_proposed_card(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    agentcore_session_id: str,
    source: str,
    source_id: str,
    snapshot: dict[str, Any],
) -> uuid.UUID | None:
    """Insert a pending-experience node for an agent-proposed card.

    Returns the new node id on success, None on persistence failure, and
    None after queueing when an advisor currently holds the lock. The
    SSE forwarder emits the card frame with ``node_id=None`` either way —
    a hard reload re-fetches the itinerary after drain, so the client
    stays consistent.

    Redaction: the snapshot dict lands in ``nodes.metadata`` (browser
    fetches it back on reload) but never appears in any log line.
    """
    title = ""
    raw_title = snapshot.get("title")
    if isinstance(raw_title, str):
        title = raw_title

    # Trunk guard: cards land in the traveler's working fork, not the trunk.
    itinerary_id = await _resolve_card_itinerary(
        session,
        itinerary_id=itinerary_id,
        session_id=session_id,
        agentcore_session_id=agentcore_session_id,
    )

    card_actor = itineraries_service.ActorContext(
        user_id=None,
        kind=itineraries_service.ActorKind.AGENT,
        actor_id=agentcore_session_id,
    )

    # Lock gate: if an advisor holds the lock, queue the mutation and bail
    # before ``add_node`` so no partial state leaks to the DB. The helper is
    # side-effect-free so reading it mid-transaction is safe.
    lock_err = await itineraries_service._check_write_gates(session, itinerary_id, card_actor)
    if lock_err is not None and lock_err.outcome is itineraries_service.ItineraryOutcome.LOCKED:
        payload: dict[str, Any] = {
            "type": NodeType.experience,
            "status": NodeStatus.pending,
            "title": title,
            "source": source,
            "source_id": source_id,
            "metadata": {"snapshot": snapshot},
        }
        _agent_write_queue.setdefault(itinerary_id, []).append(
            QueuedMutation(
                itinerary_id=itinerary_id,
                session_id=session_id,
                op="add_node",
                payload=payload,
                actor=card_actor,
                queued_at=datetime.now(UTC),
            )
        )
        logger.info(
            "itinerary.agent_write_queued",
            extra={
                "session_id": str(session_id),
                "itinerary_id": str(itinerary_id),
                "op": "add_node",
            },
        )
        return None

    result = await itineraries_service.add_node(
        session,
        card_actor,
        itinerary_id=itinerary_id,
        type=NodeType.experience,
        status=NodeStatus.pending,
        title=title,
        source=source,
        source_id=source_id,
        metadata={"snapshot": snapshot},
    )
    if isinstance(result, itineraries_service.ItineraryError):
        logger.warning(
            "agent.card.persist_failed",
            extra={
                "session_id": str(session_id),
                "source": source,
                "source_id": source_id,
                "reason": result.outcome.value,
            },
        )
        return None

    logger.info(
        "agent.card.proposed",
        extra={
            "session_id": str(session_id),
            "source": source,
            "source_id": source_id,
            "itinerary_id": str(itinerary_id),
            "node_id": str(result.id),
        },
    )
    return result.id


async def _authorize_actor(
    actor: ActorContext,
    client: Client,
) -> TurnOutcome:
    """Enforce (actor, client) ownership before any stream bytes go out."""
    if actor.actor_kind == "advisor":
        if actor.user_id is None or client.owner_id != actor.user_id:
            return TurnOutcome.SESSION_NOT_YOURS
    elif actor.actor_kind == "user" and (
        actor.user_id is None or client.auth_user_id != actor.user_id
    ):
        return TurnOutcome.SESSION_NOT_YOURS
    return TurnOutcome.OK


async def stream_turn(
    session_factory: async_sessionmaker[AsyncSession],
    runtime: AgentRuntimeClient,
    *,
    actor: ActorContext,
    session_id: uuid.UUID,
    content: str,
    auth_bearer: str | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[bytes]:
    """Orchestrate one turn end-to-end and yield SSE frames as bytes.

    Structure (matching T04 plan step-by-step):
      A. Open session A → auth + load context + compute turn_index +
         INSERT user turn → commit → close.
      B. Retry envelope around ``runtime.invoke_stream`` (only before the
         first downstream byte). Yield delta / first_token / done frames
         as they arrive, plus any unknown frame (e.g. ``card`` frames for
         S07's OV experience proposals) forwarded verbatim. On
         exhaustion, emit the crafted fallback frame.
      C. Open session B → INSERT assistant (or 'error') turn → commit.
      D. Best-effort AgentCore Memory write. Swallow failures.
    """
    settings = settings or get_settings()

    # ── A. User-write transaction ──────────────────────────────────────────
    async with session_factory() as db:
        ctx = await _load_session_context(db, session_id=session_id)
        if ctx is None:
            yield _FALLBACK_FRAME
            logger.info(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "reason": "session_not_found",
                },
            )
            return
        agent_session, client_row, dossier = ctx

        authz = await _authorize_actor(actor, client_row)
        if authz is not TurnOutcome.OK:
            yield _FALLBACK_FRAME
            logger.info(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "reason": "forbidden",
                },
            )
            return

        if not content or not content.strip():
            yield _FALLBACK_FRAME
            logger.info(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "reason": "invalid_input",
                },
            )
            return

        try:
            turn_index = await _next_turn_index(db, session_id=session_id)
        except IntegrityError:
            await db.rollback()
            yield _FALLBACK_FRAME
            logger.info(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "reason": "turn_index_conflict",
                },
            )
            return

        # Gather the three fact tiers (active rows only — agent must never
        # see redacted facts). One call yields all three lists in three
        # small SELECTs sharing the same session.
        ctx_rows = await load_agent_context(db, client_id=client_row.id)
        dossier_facts = ctx_rows.dossier_facts if ctx_rows else []
        profile_facts = ctx_rows.profile_facts if ctx_rows else []
        osint_facts = ctx_rows.osint_facts if ctx_rows else []

        # Fork-awareness (G3): if the session is pinned to a fork, frame the
        # prompt around "an alternative version" of the baseline.
        fork_baseline_title = await _fork_baseline_title(db, agent_session.itinerary_id)

        # Trip brief (0033): the goal + timing the traveler set at intake, so the
        # agent grounds its first suggestions in what they're actually planning.
        trip_brief = await trip_brief_for_itinerary(db, agent_session.itinerary_id)

        # Graph digest (AGT-2): the pinned plan's live state — lifecycle status,
        # node counts, totals, uninvoiced remainder — computed fresh per turn and
        # injected into the system prompt so the agent never has to burn a
        # get_itinerary call just to learn where the plan stands.
        graph_digest = await graph_digest_for_itinerary(db, agent_session.itinerary_id)

        # Assemble prompt + context OUTSIDE the log-safe zone.
        traveler_ctx = assemble_traveler_context(
            dossier=dossier,
            dossier_facts=dossier_facts,
            profile_facts=profile_facts,
            osint_facts=osint_facts,
            client_full_name=client_row.full_name,
            alternative_of=fork_baseline_title,
            trip_brief=trip_brief,
            graph_digest=graph_digest,
        )
        system_prompt = build_system_prompt(traveler_ctx)
        agentcore_session_id = agent_session.agentcore_session_id
        client_id = client_row.id
        actor_user_id = actor.user_id
        pinned_itinerary_id = agent_session.itinerary_id

        # Mode + prior turns — both cheap SELECTs, same transaction.
        mode = await _detect_mode(db, itinerary_id=pinned_itinerary_id, client_id=client_id)
        prior_turns = await _load_prior_turns(db, session_id=session_id)

        # Auto-title from the first user message (M006/PS2) — only when the
        # session has no title yet, so an explicit rename (PATCH) is preserved.
        # `agent_session` is attached to `db`, so the set persists on the commit
        # below alongside the user turn.
        if not agent_session.title:
            agent_session.title = _derive_session_title(content)

        user_turn = AgentTurn(
            session_id=session_id,
            turn_index=turn_index,
            role=TurnRole.user,
            content=content,
            actor_kind=actor.actor_kind,
            actor_id=actor.actor_id,
            retried=0,
        )
        db.add(user_turn)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            yield _FALLBACK_FRAME
            logger.info(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index,
                    "reason": "turn_index_conflict",
                },
            )
            return

    logger.info(
        "agent.turn.start",
        extra={
            "session_id": str(session_id),
            "turn_index": turn_index,
        },
    )

    # ── B. Retry envelope + streaming ──────────────────────────────────────
    max_retries = settings.agent_max_retries
    first_token_deadline = settings.agent_first_token_timeout_seconds
    started = time.monotonic()

    # Payload contract — new-runtime fields + the legacy ``input`` field so
    # the pre-agent-workspace runtime (out-of-band AgentCore agent) keeps
    # working while we roll out. The new apps/agent runtime reads
    # ``input_text`` and ignores ``input``; the legacy runtime was wired
    # against ``input``. Remove once the new runtime is in staging and
    # traffic has shifted.
    # Mint a per-session agent token for the runtime to call backend-only
    # /agent/* routes (Dossier+Profile+OSINT context, private fact writes).
    # The user JWT (auth_bearer) keeps its narrower scope for tools that
    # act on the user's own resources (itineraries, mutations).
    try:
        agent_token = mint_agent_token(
            session_id=session_id,
            client_id=client_id,
            agentcore_session_id=agentcore_session_id,
            settings=settings,
        )
    except AgentTokenError:
        # Local dev / unconfigured environments: ship an empty string so
        # the runtime can degrade gracefully (the new tools fail with a
        # clear ``missing_agent_token`` rather than crashing the turn).
        agent_token = ""

    payload = {
        "system": system_prompt,
        "input": [{"role": "user", "content": [{"text": content}]}],
        "input_text": content,
        "prior_turns": prior_turns,
        "mode": mode,
        "auth_bearer": auth_bearer or "",
        "agent_token": agent_token,
        "actor_kind": actor.actor_kind,
        "client_id": str(client_id),
        "itinerary_id": (str(pinned_itinerary_id) if pinned_itinerary_id else None),
        # Thread the session's audience so the fork tool can re-pin the session
        # (POST /sessions) to the right (client_id, audience) thread (G3, §4.1).
        # audience is NOT NULL in the DB; default defensively for stubs/old rows.
        "audience": (
            agent_session.audience.value if agent_session.audience is not None else "traveler"
        ),
    }

    assembled_text = ""
    first_token_ms: int | None = None
    attempt_count = 0
    fallback_fired = False
    itinerary_id_cache: uuid.UUID | None = None

    while True:
        got_first_byte = False
        try:
            stream = runtime.invoke_stream(
                agentcore_session_id=agentcore_session_id,
                payload=payload,
            )
            async with aclosing(stream) as events:
                async for event in events:
                    # First-token deadline: if we have not yet seen any event
                    # from the runtime by ``first_token_deadline``, fall into
                    # the retry envelope with ``first_token_timeout``.
                    if (
                        first_token_ms is None
                        and (time.monotonic() - started) > first_token_deadline
                    ):
                        raise TimeoutError("first_token_timeout")

                    kind = event.get("type")
                    if kind == "first_token":
                        first_token_ms = int(event.get("ms", 0))
                        logger.info(
                            "agent.turn.first_token",
                            extra={
                                "session_id": str(session_id),
                                "turn_index": turn_index,
                                "first_token_ms": first_token_ms,
                            },
                        )
                        got_first_byte = True
                        yield _sse_encode({"type": "first_token", "ms": first_token_ms})
                    elif kind == "delta":
                        text_chunk = str(event.get("text", ""))
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - started) * 1000)
                            logger.info(
                                "agent.turn.first_token",
                                extra={
                                    "session_id": str(session_id),
                                    "turn_index": turn_index,
                                    "first_token_ms": first_token_ms,
                                },
                            )
                            got_first_byte = True
                            yield _sse_encode({"type": "first_token", "ms": first_token_ms})
                        assembled_text += text_chunk
                        got_first_byte = True
                        yield _sse_encode({"type": "delta", "text": text_chunk})
                    elif kind == "done":
                        break
                    elif kind == "assemble_draft":
                        # S08: the agent has proposed a day-by-day ordering of
                        # previously-proposed card nodes. Promote the actor to
                        # AGENT and call the thick composite. Forward the event
                        # with an ``edges_created`` field — the browser doesn't
                        # do anything with it today, but the advisor surface
                        # can surface a count-to-Approve progress cue later.
                        raw_day_plan = event.get("day_plan")
                        edges_created = 0
                        forwarded_plan: list[dict[str, Any]] = []
                        malformed = False
                        parsed_plan: list[itineraries_service.DaySlot] = []
                        if not isinstance(raw_day_plan, list):
                            malformed = True
                        else:
                            for slot in raw_day_plan:
                                if not isinstance(slot, dict):
                                    malformed = True
                                    break
                                day_index = slot.get("day_index")
                                node_ids_raw = slot.get("node_ids_in_order")
                                if not isinstance(day_index, int) or not isinstance(
                                    node_ids_raw, list
                                ):
                                    malformed = True
                                    break
                                parsed_ids: list[uuid.UUID] = []
                                id_strs: list[str] = []
                                for nid in node_ids_raw:
                                    if not isinstance(nid, str):
                                        malformed = True
                                        break
                                    try:
                                        parsed_ids.append(uuid.UUID(nid))
                                    except (TypeError, ValueError):
                                        malformed = True
                                        break
                                    id_strs.append(nid)
                                if malformed:
                                    break
                                parsed_plan.append(
                                    {
                                        "day_index": day_index,
                                        "node_ids_in_order": parsed_ids,
                                    }
                                )
                                forwarded_plan.append(
                                    {
                                        "day_index": day_index,
                                        "node_ids_in_order": id_strs,
                                    }
                                )

                        if malformed:
                            logger.info(
                                "agent.assemble_draft.malformed",
                                extra={"session_id": str(session_id)},
                            )
                            got_first_byte = True
                            yield _sse_encode(
                                {
                                    "type": "assemble_draft",
                                    "day_plan": forwarded_plan,
                                    "edges_created": 0,
                                }
                            )
                            continue

                        async with session_factory() as card_db:
                            if itinerary_id_cache is None:
                                itinerary_id_cache = await _ensure_itinerary_for_client(
                                    card_db,
                                    client_id=client_id,
                                    actor_user_id=actor_user_id,
                                )
                            assemble_actor = itineraries_service.ActorContext(
                                user_id=None,
                                kind=itineraries_service.ActorKind.AGENT,
                                actor_id=agentcore_session_id,
                            )
                            result = await itineraries_service.assemble_initial_draft(
                                card_db,
                                assemble_actor,
                                itinerary_id=itinerary_id_cache,
                                day_plan=parsed_plan,
                            )
                            if isinstance(result, itineraries_service.ItineraryError):
                                logger.info(
                                    "agent.assemble_draft.failed",
                                    extra={
                                        "session_id": str(session_id),
                                        "itinerary_id": str(itinerary_id_cache),
                                        "reason": result.outcome.value,
                                    },
                                )
                                edges_created = 0
                            else:
                                edges_created = len(result.edges)

                        got_first_byte = True
                        yield _sse_encode(
                            {
                                "type": "assemble_draft",
                                "day_plan": forwarded_plan,
                                "edges_created": edges_created,
                            }
                        )
                    elif kind == "card":
                        # S07: persist the card as a proposed-experience node
                        # BEFORE forwarding so a hard reload can rehydrate it.
                        # Persistence failure is non-fatal — the frame still
                        # flows to the browser.
                        source = event.get("source")
                        source_id = event.get("source_id")
                        snapshot = event.get("snapshot")
                        if (
                            not isinstance(source, str)
                            or not isinstance(source_id, str)
                            or not isinstance(snapshot, dict)
                        ):
                            logger.info(
                                "agent.card.malformed",
                                extra={
                                    "session_id": str(session_id),
                                    "source": source if isinstance(source, str) else None,
                                    "source_id": (
                                        source_id if isinstance(source_id, str) else None
                                    ),
                                },
                            )
                            got_first_byte = True
                            yield _sse_encode(event)
                            continue

                        node_id: uuid.UUID | None = None
                        async with session_factory() as card_db:
                            if itinerary_id_cache is None:
                                itinerary_id_cache = await _ensure_itinerary_for_client(
                                    card_db,
                                    client_id=client_id,
                                    actor_user_id=actor_user_id,
                                )
                            node_id = await _persist_proposed_card(
                                card_db,
                                session_id=session_id,
                                itinerary_id=itinerary_id_cache,
                                agentcore_session_id=agentcore_session_id,
                                source=source,
                                source_id=source_id,
                                snapshot=snapshot,
                            )

                        forwarded = {
                            "type": "card",
                            "source": source,
                            "source_id": source_id,
                            "snapshot": snapshot,
                            "node_id": str(node_id) if node_id is not None else None,
                        }
                        got_first_byte = True
                        yield _sse_encode(forwarded)
                    else:
                        # Unknown event type — forward unchanged.
                        got_first_byte = True
                        yield _sse_encode(event)
            break  # Clean exit from the retry envelope.
        except (AgentRuntimeError, TimeoutError) as exc:
            # Retry only if we haven't emitted a byte yet AND have budget left.
            reason = exc.reason if isinstance(exc, AgentRuntimeError) else "first_token_timeout"
            if got_first_byte:
                # Mid-stream failure — no retry, just crash out to fallback.
                logger.warning(
                    "agent.turn.upstream_unavailable",
                    extra={
                        "session_id": str(session_id),
                        "turn_index": turn_index,
                        "reason": reason,
                    },
                )
                fallback_fired = True
                break
            if attempt_count >= max_retries:
                logger.warning(
                    "agent.turn.upstream_unavailable",
                    extra={
                        "session_id": str(session_id),
                        "turn_index": turn_index,
                        "reason": reason,
                    },
                )
                fallback_fired = True
                break
            attempt_count += 1
            backoff = min(
                2**attempt_count * 0.25 + random.uniform(0, 0.25),
                2.0,
            )
            logger.info(
                "agent.turn.retry",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index,
                    "attempt": attempt_count,
                    "reason": reason,
                },
            )
            await anyio.sleep(backoff)
            continue

    if fallback_fired:
        yield _FALLBACK_FRAME

    # ── C. Emit terminal done + assistant-write transaction ────────────────
    latency_ms = int((time.monotonic() - started) * 1000)
    new_turn_id = uuid.uuid4()
    yield _sse_encode(
        {
            "type": "done",
            "turn_id": str(new_turn_id),
            "latency_ms": latency_ms,
        }
    )

    model_tag = _arn_tail(settings.bedrock_agentcore_runtime_arn)

    async with session_factory() as db:
        assistant_turn = AgentTurn(
            id=new_turn_id,
            session_id=session_id,
            turn_index=turn_index + 1,
            role=TurnRole.error if fallback_fired else TurnRole.assistant,
            content="" if fallback_fired else assembled_text,
            model=model_tag,
            latency_ms=latency_ms,
            first_token_ms=first_token_ms if not fallback_fired else None,
            actor_kind="agent",
            actor_id=agentcore_session_id,
            retried=attempt_count,
            error_reason="upstream_unavailable" if fallback_fired else None,
        )
        db.add(assistant_turn)
        try:
            await db.commit()
        except IntegrityError:
            # Best-effort: the stream has already been emitted to the user,
            # so we cannot recover here — just log and move on.
            await db.rollback()
            logger.warning(
                "agent.turn.upstream_unavailable",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index + 1,
                    "reason": "assistant_write_conflict",
                },
            )
            return

    logger.info(
        "agent.turn.complete",
        extra={
            "session_id": str(session_id),
            "turn_index": turn_index + 1,
            "turn_id": str(new_turn_id),
            "latency_ms": latency_ms,
            "retried": attempt_count,
            "model": model_tag,
        },
    )

    # Turn-level SLO metrics (R015: 2 s first-token target). Outcome dimension
    # lets a dashboard split healthy turns from fallbacks; first-token is the
    # number to alert on. No content — ids/latency only.
    outcome = "fallback" if fallback_fired else "ok"
    emit_metric(
        "agent.turn.latency", latency_ms, unit="Milliseconds", dimensions={"Outcome": outcome}
    )
    emit_metric(
        "agent.turn.count", 1, dimensions={"Outcome": outcome, "Retried": str(attempt_count)}
    )
    if first_token_ms is not None:
        emit_metric(
            "agent.turn.first_token",
            first_token_ms,
            unit="Milliseconds",
            dimensions={"Outcome": outcome},
        )

    # ── D. Best-effort AgentCore Memory write ──────────────────────────────
    memory_id = settings.bedrock_agentcore_memory_id
    if memory_id and not fallback_fired:
        try:
            await runtime.create_event(
                memory_id=memory_id,
                agentcore_session_id=agentcore_session_id,
                user_text=content,
                assistant_text=assembled_text,
            )
            logger.info(
                "agent.memory.create_event",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index + 1,
                },
            )
        except Exception as exc:  # noqa: BLE001 — failure must never raise
            reason = exc.reason if isinstance(exc, AgentRuntimeError) else exc.__class__.__name__
            logger.warning(
                "agent.memory.create_event.failed",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index + 1,
                    "reason": reason,
                },
            )


# ── PS8: Artemis-in-human-chat bridge (@-mention) ──────────────────────────
#
# A human posts into a human thread; if their message @-mentions Artemis, we run
# ONE thread-scoped agent turn and insert a single ``author_kind='artemis'``
# message. The whole thread (traveler + advisor + party) sees it, so the reply
# MUST be client-safe — which is why :func:`summon_artemis_in_thread` takes no
# summoner principal at all: disclosure follows the thread's audience, never who
# typed the mention. Proposals still flow to the single graph. Redaction
# discipline from ``stream_turn`` applies verbatim — trigger / reply / context
# text is never logged.

# The mention trigger: a standalone, case-insensitive ``@artemis`` token. The
# lookbehind rejects an ``@`` glued to a word (so ``name@artemis.example`` never
# fires). First and, this slice, only summon trigger.
_MENTION_RE = re.compile(r"(?<![\w@])@artemis\b", re.IGNORECASE)


def mentions_artemis(content: str) -> bool:
    """True when a human message summons Artemis via an @-mention."""
    return _MENTION_RE.search(content) is not None


def strip_mention(content: str) -> str:
    """Drop the @Artemis token so the model reads the plain request.

    Collapses the whitespace the removed token leaves behind. A bare ``@Artemis``
    with nothing else falls back to a neutral opener so the turn still has input.
    """
    stripped = " ".join(_MENTION_RE.sub("", content).split()).strip()
    return stripped or "Hello — how can you help with this trip?"


async def _get_or_create_thread_engine(db: AsyncSession, *, thread: Thread) -> AgentSession:
    """Get — or create — the one ``AgentSession`` that is a human thread's engine.

    Q13 = UNIFY forward hook: a thread binds exactly one ``agent_session`` via
    ``thread_id``. For a human thread this is the engine Artemis runs on when
    summoned — a stable ``agentcore_session_id`` (AgentCore Memory continuity
    across summons) plus the itinerary pin for card provenance. It is NOT a
    standing participant: no ``thread_participants`` row is seeded (Artemis is
    summoned per-turn, not seated). Get-or-create keyed on ``thread_id``.
    """
    engine = (
        await db.execute(
            select(AgentSession)
            .where(AgentSession.thread_id == thread.id, AgentSession.ended_at.is_(None))
            .order_by(AgentSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if engine is not None:
        return engine
    engine = AgentSession(
        client_id=thread.client_id,
        agentcore_session_id=str(uuid.uuid4()),
        itinerary_id=thread.itinerary_id,
        audience=thread.audience,
        thread_id=thread.id,
    )
    db.add(engine)
    await db.commit()
    await db.refresh(engine)
    return engine


async def _load_thread_prior_turns(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    exclude_message_id: uuid.UUID | None,
    limit: int = 20,
) -> list[dict[str, str]]:
    """The recent human-visible transcript as model turns, oldest-first.

    The thread's ``messages`` ARE the conversation history (UNIFY): a traveler or
    advisor message maps to ``user``, an Artemis message to ``assistant``, and
    ``system`` notices are skipped. The just-posted trigger is excluded — it
    becomes the current input. Best-effort: a miss just starts the model fresh.
    """
    try:
        stmt = (
            select(Message.author_kind, Message.content)
            .where(
                Message.thread_id == thread_id,
                Message.removed_at.is_(None),
                Message.author_kind != ThreadActorKind.system,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        if exclude_message_id is not None:
            stmt = stmt.where(Message.id != exclude_message_id)
        rows = (await db.execute(stmt)).all()
    except (SQLAlchemyError, AssertionError):
        return []
    turns: list[dict[str, str]] = []
    for author_kind, content in reversed(rows):
        role = "assistant" if author_kind is ThreadActorKind.artemis else "user"
        turns.append({"role": role, "content": content})
    return turns


async def summon_artemis_in_thread(
    session_factory: async_sessionmaker[AsyncSession],
    runtime: AgentRuntimeClient,
    *,
    thread_id: uuid.UUID,
    trigger_content: str,
    trigger_message_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> uuid.UUID | None:
    """Summon Artemis into a HUMAN thread; insert one ``author_kind='artemis'``
    message and return its id (or ``None`` if nothing was said).

    **Disclosure invariant.** This function takes NO summoner principal. The reply
    is assembled from the THREAD's audience — a human thread is always
    ``traveler`` — so an advisor-summoned reply in a client-visible thread stays
    client-safe *by construction*. There is no code path by which who typed
    "@Artemis" could widen disclosure or tool scope.

    **Proposals land on the spine.** A ``card`` frame is persisted as a
    proposed-experience node (AGENT actor, same path as ``stream_turn``) and the
    first new node id is attached to the Artemis message's ``proposed_node_id``.

    **Best-effort.** On any upstream failure the human message stands alone (no
    Artemis reply) and we return ``None``. Redaction: trigger / reply / context
    text is NEVER logged — ids + counts only.
    """
    settings = settings or get_settings()

    # ── Load the thread + its client context (audience-scoped, not summoner) ─
    async with session_factory() as db:
        thread = (
            await db.execute(select(Thread).where(Thread.id == thread_id))
        ).scalar_one_or_none()
        if thread is None or thread.kind is not ThreadKind.human:
            # Only human threads summon Artemis; ai_session threads run their own
            # turn path. Nothing to do here.
            return None

        ctx_rows = await load_agent_context(db, client_id=thread.client_id)
        if ctx_rows is None:
            return None

        engine = await _get_or_create_thread_engine(db, thread=thread)
        engine_id = engine.id
        agentcore_session_id = engine.agentcore_session_id
        client_id = thread.client_id
        itinerary_id = thread.itinerary_id
        # A human thread is always audience='traveler'; default defensively.
        audience_value = thread.audience.value if thread.audience is not None else "traveler"

        # Same client-safe context a traveler turn would get — the summoner is
        # never consulted, so the disclosure boundary is the thread's.
        fork_baseline_title = await _fork_baseline_title(db, itinerary_id)
        trip_brief = await trip_brief_for_itinerary(db, itinerary_id)
        traveler_ctx = assemble_traveler_context(
            dossier=ctx_rows.dossier,
            dossier_facts=ctx_rows.dossier_facts,
            profile_facts=ctx_rows.profile_facts,
            osint_facts=ctx_rows.osint_facts,
            client_full_name=ctx_rows.client.full_name,
            alternative_of=fork_baseline_title,
            trip_brief=trip_brief,
        )
        system_prompt = build_system_prompt(traveler_ctx)
        mode = await _detect_mode(db, itinerary_id=itinerary_id, client_id=client_id)
        prior_turns = await _load_thread_prior_turns(
            db, thread_id=thread_id, exclude_message_id=trigger_message_id
        )

    # ── Mint the backend agent token (best-effort) ─────────────────────────
    try:
        agent_token = mint_agent_token(
            session_id=engine_id,
            client_id=client_id,
            agentcore_session_id=agentcore_session_id,
            settings=settings,
        )
    except AgentTokenError:
        agent_token = ""

    input_text = strip_mention(trigger_content)
    payload = {
        "system": system_prompt,
        "input": [{"role": "user", "content": [{"text": input_text}]}],
        "input_text": input_text,
        "prior_turns": prior_turns,
        "mode": mode,
        # No summoner bearer: a summoned reply acts only through the AGENT-actor
        # card path, never a user's own token — an advisor summon can't widen
        # tool scope inside a client-visible thread.
        "auth_bearer": "",
        "agent_token": agent_token,
        # Client-facing framing — disclosure + tool scope follow the THREAD.
        "actor_kind": "user",
        "client_id": str(client_id),
        "itinerary_id": str(itinerary_id) if itinerary_id else None,
        "audience": audience_value,
    }

    # ── Run one turn: accumulate prose + capture the first card proposal ────
    assembled_text = ""
    proposed_node_id: uuid.UUID | None = None
    itinerary_id_cache: uuid.UUID | None = itinerary_id
    try:
        stream = runtime.invoke_stream(agentcore_session_id=agentcore_session_id, payload=payload)
        async with aclosing(stream) as events:
            async for event in events:
                kind = event.get("type")
                if kind == "delta":
                    assembled_text += str(event.get("text", ""))
                elif kind == "card":
                    source = event.get("source")
                    source_id = event.get("source_id")
                    snapshot = event.get("snapshot")
                    if not (
                        isinstance(source, str)
                        and isinstance(source_id, str)
                        and isinstance(snapshot, dict)
                    ):
                        continue
                    async with session_factory() as card_db:
                        if itinerary_id_cache is None:
                            itinerary_id_cache = await _ensure_itinerary_for_client(
                                card_db, client_id=client_id, actor_user_id=None
                            )
                        node_id = await _persist_proposed_card(
                            card_db,
                            session_id=engine_id,
                            itinerary_id=itinerary_id_cache,
                            agentcore_session_id=agentcore_session_id,
                            source=source,
                            source_id=source_id,
                            snapshot=snapshot,
                        )
                    if proposed_node_id is None:
                        proposed_node_id = node_id
                elif kind == "done":
                    break
                # Other frames (first_token / assemble_draft / unknown) have no
                # live SSE consumer in the human-thread bridge — ignore them.
    except (AgentRuntimeError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, AgentRuntimeError) else "first_token_timeout"
        logger.warning(
            "agent.summon.upstream_unavailable",
            extra={"thread_id": str(thread_id), "reason": reason},
        )
        return None

    content = assembled_text.strip()
    if not content:
        if proposed_node_id is not None:
            content = "I've added a suggestion to your itinerary — take a look."
        else:
            logger.info("agent.summon.empty", extra={"thread_id": str(thread_id)})
            return None

    # ── Insert the Artemis message (author_kind='artemis', author_id NULL) ──
    async with session_factory() as db:
        message = Message(
            thread_id=thread_id,
            author_kind=ThreadActorKind.artemis,
            author_id=None,
            content=content,
            proposed_node_id=proposed_node_id,
            parent_message_id=trigger_message_id,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        message_id = message.id

    logger.info(
        "agent.summon.complete",
        extra={
            "thread_id": str(thread_id),
            "message_id": str(message_id),
            "proposed_node_id": str(proposed_node_id) if proposed_node_id else None,
        },
    )
    return message_id
