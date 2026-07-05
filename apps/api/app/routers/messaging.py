"""Human messaging HTTP surface — /threads (M006/PS7).

Three routes, all gated by the standard JWT middleware:

- ``POST /threads``                       get-or-create the human thread for a scope
- ``GET  /threads/{id}/messages``         list a thread's human messages
- ``POST /threads/{id}/messages``         post one human message (NO agent turn)

Authorization mirrors the /sessions surface: an advisor who owns the client, or
the client themself. Every access failure collapses to a JSON 404 (D015) so a
caller cannot probe which threads or clients exist. Artemis is not summoned here
— that is PS8's @-mention bridge; PS7 is a pure human channel.

Redaction discipline: message ``content`` is never logged in this module (the
service handles the id-only log events).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.auth import AuthenticatedUser, require_user
from app.db import get_session, get_sessionmaker
from app.routers.agent import _actor_for_user
from app.schemas.messaging import (
    MessageSummary,
    OpenThreadRequest,
    SendMessageRequest,
    ThreadSummary,
)
from app.services.agent import mentions_artemis, summon_artemis_in_thread
from app.services.messaging import (
    MessagingOutcome,
    list_messages,
    open_or_create_human_thread,
    send_message,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Message, Thread

logger = logging.getLogger("ov_black.routers.messaging")

router = APIRouter(prefix="/threads", tags=["threads"])


def _thread_summary(thread: Thread) -> ThreadSummary:
    return ThreadSummary(
        thread_id=thread.id,
        client_id=thread.client_id,
        itinerary_id=thread.itinerary_id,
        kind=thread.kind,
        audience=thread.audience,
        title=thread.title,
        created_at=thread.created_at,
    )


def _message_summary(message: Message) -> MessageSummary:
    return MessageSummary(
        id=message.id,
        thread_id=message.thread_id,
        author_kind=message.author_kind,
        author_id=message.author_id,
        content=message.content,
        proposed_node_id=message.proposed_node_id,
        parent_message_id=message.parent_message_id,
        created_at=message.created_at,
        edited_at=message.edited_at,
    )


# ── POST /threads ────────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ThreadSummary,
    responses={
        201: {"description": "Human thread resolved — get-or-create, idempotent."},
        404: {"description": "No client/itinerary with this id accessible to the caller."},
    },
    summary="Get or create the human thread for a scope (client / itinerary).",
)
async def open_thread_endpoint(
    payload: OpenThreadRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ThreadSummary:
    actor = await _actor_for_user(user, session)
    outcome, thread = await open_or_create_human_thread(
        session,
        actor=actor,
        client_id=payload.client_id,
        itinerary_id=payload.itinerary_id,
    )
    if outcome is not MessagingOutcome.OK or thread is None:
        # Collapsed 404 (D015): FORBIDDEN and CLIENT_NOT_FOUND both land here so a
        # caller cannot probe existence of a client / foreign itinerary.
        raise HTTPException(status_code=404, detail="thread_not_found")
    return _thread_summary(thread)


# ── GET /threads/{id}/messages ───────────────────────────────────────────────


@router.get(
    "/{thread_id}/messages",
    response_model=list[MessageSummary],
    responses={
        404: {"description": "No thread with this id accessible to the caller."},
    },
    summary="List a thread's human messages, oldest first.",
)
async def list_messages_endpoint(
    thread_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageSummary]:
    actor = await _actor_for_user(user, session)
    outcome, rows = await list_messages(session, actor=actor, thread_id=thread_id)
    if outcome is not MessagingOutcome.OK:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return [_message_summary(m) for m in rows]


# ── POST /threads/{id}/messages ──────────────────────────────────────────────


@router.post(
    "/{thread_id}/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageSummary,
    responses={
        201: {"description": "Human message posted; @Artemis summons a reply async."},
        404: {"description": "No thread with this id accessible to the caller."},
        422: {"description": "Invalid content body (empty or > 8000 chars)."},
    },
    summary="Post one human message; an @Artemis mention summons a reply (PS8).",
)
async def send_message_endpoint(
    thread_id: uuid.UUID,
    payload: SendMessageRequest,
    request: Request,
    background: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MessageSummary:
    actor = await _actor_for_user(user, session)
    outcome, message = await send_message(
        session,
        actor=actor,
        thread_id=thread_id,
        content=payload.content,
        parent_message_id=payload.parent_message_id,
    )
    if outcome is not MessagingOutcome.OK or message is None:
        raise HTTPException(status_code=404, detail="thread_not_found")

    # PS8 @-mention bridge: if the human summoned Artemis, run the thread-scoped
    # turn AFTER the response so the sender's own message lands instantly and the
    # Artemis reply arrives on the next poll. Disclosure follows the thread, not
    # this sender — the bridge takes no principal (see summon_artemis_in_thread).
    # Skip silently when no runtime is wired (local dev without an agent): the
    # human message still posts.
    if mentions_artemis(payload.content):
        runtime = getattr(request.app.state, "agent_runtime", None)
        if runtime is not None:
            background.add_task(
                summon_artemis_in_thread,
                get_sessionmaker(),
                runtime,
                thread_id=thread_id,
                trigger_content=payload.content,
                trigger_message_id=message.id,
            )
    return _message_summary(message)
