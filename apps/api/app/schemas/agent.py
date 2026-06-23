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

from app.models import SessionAudience, TurnRole


class OpenSessionRequest(BaseModel):
    """Payload for ``POST /sessions``.

    ``itinerary_id`` is optional: pin the session to a specific draft for
    planning mode, or omit for a general session (onboarding / Q&A). A
    session pinned to an approved itinerary serves as a trip-scoped Q&A.

    ``seeded_opener`` is the verbatim opening line the basecamp UI picked
    from the onboarding-opener bank for a brand-new client. It is recorded
    on the session row and replayed on the runtime as a mode-rubric
    directive ("your first message MUST be exactly …") so the agent's
    streamed first turn matches the prompt the user already saw on the
    page. Ignored / persisted-but-no-op for non-onboarding sessions.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    itinerary_id: uuid.UUID | None = None
    seeded_opener: Annotated[str, Field(max_length=500)] | None = None
    # Which conversation to open. ``traveler`` (default) is the client-facing
    # thread — the existing behaviour, so travelers / basecamp / the chat page
    # are unaffected. ``advisor`` opens a private advisor<->AI workspace the
    # traveler never sees; only an advisor actor may request it.
    audience: SessionAudience = SessionAudience.traveler


class OpenSessionResponse(BaseModel):
    """Response for ``POST /sessions`` — returned on both create and reuse.

    ``itinerary_id`` reflects the session's current pin. ``None`` means the
    session is unpinned — the browser's mood-board aside can either stay
    empty (onboarding / Q&A) or hydrate after the first ``card_proposed``
    frame auto-creates one. ``seeded_opener`` round-trips so the caller
    can verify the persisted value matches what they sent (for reused
    sessions, this may be a value chosen on a prior request).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    agentcore_session_id: str
    itinerary_id: uuid.UUID | None
    seeded_opener: str | None = None
    audience: SessionAudience = SessionAudience.traveler


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
