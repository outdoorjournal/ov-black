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
   fallback frame. All frames flow from this module as raw ``bytes`` so
   the router layer is a thin conduit.

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
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from contextlib import aclosing

import anyio
from sqlalchemy import func, select, text as sql_text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bedrock import AgentRuntimeClient, AgentRuntimeError
from app.agent.prompt import build_system_prompt
from app.agent.voodoo_doll_context import assemble_context
from app.config import Settings, get_settings
from app.models import AgentSession, AgentTurn, Client, TurnRole, VoodooDoll

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
_FALLBACK_FRAME: bytes = (
    b'data: {"type":"error","reason":"upstream_unavailable"}\n\n'
)


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
      - user: must be the redeemed client (clients.auth_user_id == actor.user_id).
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
    elif actor.actor_kind == "user":
        if actor.user_id is None or client.auth_user_id != actor.user_id:
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
    redeems their magic-link invite they have an ``auth.users`` row but the
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

    try:
        await session.execute(
            update(Client)
            .where(Client.id == client.id, Client.auth_user_id.is_(None))
            .values(auth_user_id=user_id)
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
    return True


async def open_or_reuse_session(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
) -> tuple[SessionOutcome, AgentSession | None]:
    """Idempotently open an AgentSession for a client.

    If an open session exists (``ended_at IS NULL``), return it; else INSERT
    one with a fresh ``agentcore_session_id``. Caller cannot distinguish
    reuse from create from the HTTP surface — both return 201 above. We
    *do* emit different log events so observability can tell the two apart.
    """
    async with session_factory() as session:
        client = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalar_one_or_none()
        if client is None:
            return SessionOutcome.CLIENT_NOT_FOUND, None

        # JIT-backfill the client↔auth.users link on the first POST /sessions
        # made by the client themself. Only runs when the link is missing and
        # the caller's JWT sub points at an auth.users row whose email matches.
        backfilled = False
        if (
            actor.actor_kind == "user"
            and actor.user_id is not None
            and client.auth_user_id is None
        ):
            backfilled = await _jit_backfill_client_auth_user_id(
                session, client=client, user_id=actor.user_id
            )

        # Access check against the (possibly-updated) client row.
        if actor.actor_kind == "advisor":
            if actor.user_id is None or client.owner_id != actor.user_id:
                return SessionOutcome.FORBIDDEN, None
        elif actor.actor_kind == "user":
            if actor.user_id is None or client.auth_user_id != actor.user_id:
                return SessionOutcome.FORBIDDEN, None
        # actor_kind == 'agent' is internal — no additional gate here.

        existing = (
            await session.execute(
                select(AgentSession).where(
                    AgentSession.client_id == client_id,
                    AgentSession.ended_at.is_(None),
                )
            )
        ).scalar_one_or_none()
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
                },
            )
            return SessionOutcome.OK, existing

        new = AgentSession(
            client_id=client_id,
            agentcore_session_id=str(uuid.uuid4()),
        )
        session.add(new)
        await session.commit()
        await session.refresh(new)
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
            },
        )
        return SessionOutcome.OK, new


# ── list_turns ─────────────────────────────────────────────────────────────


async def list_turns(
    session: AsyncSession,
    *,
    actor: ActorContext,
    session_id: uuid.UUID,
) -> list[AgentTurn] | TurnOutcome:
    """Return every turn in a session ordered by turn_index.

    Returns a ``TurnOutcome`` on failure so the router layer can map to
    404 / 403 without leaking DB internals.
    """
    agent_session = (
        await session.execute(
            select(AgentSession).where(AgentSession.id == session_id)
        )
    ).scalar_one_or_none()
    if agent_session is None:
        return TurnOutcome.SESSION_NOT_FOUND

    access = await _enforce_client_access(
        session, actor=actor, client_id=agent_session.client_id
    )
    if access is SessionOutcome.CLIENT_NOT_FOUND:
        return TurnOutcome.SESSION_NOT_FOUND
    if access is SessionOutcome.FORBIDDEN:
        return TurnOutcome.SESSION_NOT_YOURS

    rows = (
        await session.execute(
            select(AgentTurn)
            .where(AgentTurn.session_id == session_id)
            .order_by(AgentTurn.turn_index)
        )
    ).scalars().all()
    return list(rows)


# ── stream_turn ────────────────────────────────────────────────────────────


async def _load_session_context(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> tuple[AgentSession, Client, VoodooDoll] | None:
    """Join agent_session → client → voodoo_doll in one round trip."""
    row = (
        await session.execute(
            select(AgentSession, Client, VoodooDoll)
            .join(Client, Client.id == AgentSession.client_id)
            .join(VoodooDoll, VoodooDoll.client_id == Client.id)
            .where(AgentSession.id == session_id)
        )
    ).first()
    if row is None:
        return None
    agent_session, client, doll = row
    return agent_session, client, doll


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
        select(AgentSession.id)
        .where(AgentSession.id == session_id)
        .with_for_update()
    )
    current_max = (
        await session.execute(
            select(func.max(AgentTurn.turn_index)).where(
                AgentTurn.session_id == session_id
            )
        )
    ).scalar_one()
    return 0 if current_max is None else int(current_max) + 1


async def _authorize_actor(
    actor: ActorContext,
    client: Client,
) -> TurnOutcome:
    """Enforce (actor, client) ownership before any stream bytes go out."""
    if actor.actor_kind == "advisor":
        if actor.user_id is None or client.owner_id != actor.user_id:
            return TurnOutcome.SESSION_NOT_YOURS
    elif actor.actor_kind == "user":
        if actor.user_id is None or client.auth_user_id != actor.user_id:
            return TurnOutcome.SESSION_NOT_YOURS
    return TurnOutcome.OK


async def stream_turn(
    session_factory: async_sessionmaker[AsyncSession],
    runtime: AgentRuntimeClient,
    *,
    actor: ActorContext,
    session_id: uuid.UUID,
    content: str,
    settings: Settings | None = None,
) -> AsyncIterator[bytes]:
    """Orchestrate one turn end-to-end and yield SSE frames as bytes.

    Structure (matching T04 plan step-by-step):
      A. Open session A → auth + load context + compute turn_index +
         INSERT user turn → commit → close.
      B. Retry envelope around ``runtime.invoke_stream`` (only before the
         first downstream byte). Yield delta / first_token / done frames
         as they arrive. On exhaustion, emit the crafted fallback frame.
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
        agent_session, client_row, doll = ctx

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

        # Assemble prompt + context OUTSIDE the log-safe zone.
        doll_context = assemble_context(doll, client_full_name=client_row.full_name)
        system_prompt = build_system_prompt(doll_context)
        agentcore_session_id = agent_session.agentcore_session_id

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

    payload = {
        "system": system_prompt,
        "input": [{"role": "user", "content": [{"text": content}]}],
    }

    assembled_text = ""
    first_token_ms: int | None = None
    attempt_count = 0
    fallback_fired = False

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
                        yield _sse_encode(
                            {"type": "first_token", "ms": first_token_ms}
                        )
                    elif kind == "delta":
                        text_chunk = str(event.get("text", ""))
                        if first_token_ms is None:
                            first_token_ms = int(
                                (time.monotonic() - started) * 1000
                            )
                            logger.info(
                                "agent.turn.first_token",
                                extra={
                                    "session_id": str(session_id),
                                    "turn_index": turn_index,
                                    "first_token_ms": first_token_ms,
                                },
                            )
                            got_first_byte = True
                            yield _sse_encode(
                                {"type": "first_token", "ms": first_token_ms}
                            )
                        assembled_text += text_chunk
                        got_first_byte = True
                        yield _sse_encode({"type": "delta", "text": text_chunk})
                    elif kind == "done":
                        break
                    else:
                        # Unknown event type — forward unchanged.
                        got_first_byte = True
                        yield _sse_encode(event)
            break  # Clean exit from the retry envelope.
        except (AgentRuntimeError, TimeoutError) as exc:
            # Retry only if we haven't emitted a byte yet AND have budget left.
            reason = (
                exc.reason
                if isinstance(exc, AgentRuntimeError)
                else "first_token_timeout"
            )
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
            reason = (
                exc.reason
                if isinstance(exc, AgentRuntimeError)
                else exc.__class__.__name__
            )
            logger.warning(
                "agent.memory.create_event.failed",
                extra={
                    "session_id": str(session_id),
                    "turn_index": turn_index + 1,
                    "reason": reason,
                },
            )


