"""Request/response payloads for the /sessions agent surface (M001/S04 T05).

Three shapes:

- :class:`OpenSessionRequest` / :class:`OpenSessionResponse` — what ``POST
  /sessions`` expects and returns. The response is idempotent: callers
  cannot tell create from reuse.
- :class:`TurnRequest` — what ``POST /sessions/{id}/turn`` accepts as its
  body. The 8000-char cap on ``content`` is the payload-amplification
  belt (R-PRIVACY, threat surface).
- :class:`AgentTurnSummary` — read-through shape for ``GET
  /sessions/{id}/turns`` (Command Center replay, S08).

Nothing here touches SQLAlchemy — the router translates between the
Pydantic payload and the ORM rows the service returns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models import TurnRole


class OpenSessionRequest(BaseModel):
    """Payload for ``POST /sessions``."""

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID


class OpenSessionResponse(BaseModel):
    """Response for ``POST /sessions`` — returned on both create and reuse."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    agentcore_session_id: str


class TurnRequest(BaseModel):
    """Body of ``POST /sessions/{session_id}/turn``.

    ``content`` is bounded to 8000 chars to cap payload amplification into
    the Bedrock model context (threat surface). Empty strings are 422.
    """

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1, max_length=8000)]


class AgentTurnSummary(BaseModel):
    """Row shape for ``GET /sessions/{session_id}/turns``."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    turn_index: int
    role: TurnRole
    content: str
    model: str | None
    latency_ms: int | None
    first_token_ms: int | None
    retried: int
    error_reason: str | None
    created_at: datetime
