"""Request/response payloads for the /threads human-messaging surface (M006/PS7).

The human channel behind the concierge's "Advisor" people-circle: resolve the
one thread for a scope, list its messages, post a human message (no agent turn).
Nothing here touches SQLAlchemy — the router translates between these Pydantic
shapes and the ORM rows the messaging service returns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import SessionAudience, ThreadActorKind, ThreadKind


class OpenThreadRequest(BaseModel):
    """Payload for ``POST /threads`` — get-or-create the human thread for a scope.

    ``itinerary_id`` omitted / None = basecamp scope (you ↔ advisor); provided =
    that trip's thread (you ↔ advisor ↔ party). Idempotent: callers cannot tell
    create from reuse.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    itinerary_id: uuid.UUID | None = None


class ThreadSummary(BaseModel):
    """Response for ``POST /threads`` — the resolved conversation container."""

    model_config = ConfigDict(extra="forbid")

    thread_id: uuid.UUID
    client_id: uuid.UUID
    itinerary_id: uuid.UUID | None = None
    kind: ThreadKind
    audience: SessionAudience
    title: str | None = None
    created_at: datetime


class SendMessageRequest(BaseModel):
    """Body of ``POST /threads/{thread_id}/messages``.

    ``content`` is bounded to 8000 chars (mirrors the turn cap). Empty is 422.
    ``parent_message_id`` threads a reply; omit for a top-level message.
    """

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=8000)]
    parent_message_id: uuid.UUID | None = None


class MessageSummary(BaseModel):
    """Row shape for the message list + the just-sent message.

    ``author_kind`` is the explicit attribution — ``artemis`` marks an AI-authored
    message once the PS8 bridge lands; PS7 only ever emits human kinds.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    thread_id: uuid.UUID
    author_kind: ThreadActorKind
    author_id: uuid.UUID | None = None
    content: str
    proposed_node_id: uuid.UUID | None = None
    parent_message_id: uuid.UUID | None = None
    created_at: datetime
    edited_at: datetime | None = None
