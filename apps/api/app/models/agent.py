from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class TurnRole(str, enum.Enum):
    """Mirrors the public.turn_role Postgres enum from 0004_agent_sessions.sql."""

    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"
    error = "error"


# Reuse the Postgres-side enum type — SQLAlchemy must not CREATE TYPE (D003/D020).
# postgresql.ENUM exposes create_type as a real attribute (generic sqlalchemy.Enum
# silently drops it), so schema-drift tests can regression-guard this directly.
turn_role_enum = PGEnum(
    TurnRole,
    name="turn_role",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class SessionAudience(str, enum.Enum):
    """Mirrors the public.session_audience enum from 0018.

    Splits the client-facing conversation from a private advisor workspace:
    ``traveler`` is the shared thread (the traveler + any advisor who joins);
    ``advisor`` is the advisor<->AI session the traveler never sees.
    """

    traveler = "traveler"
    advisor = "advisor"


# Postgres owns the type (D003/D020); SQLAlchemy binds with create_type=False.
session_audience_enum = PGEnum(
    SessionAudience,
    name="session_audience",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class AgentSession(Base):
    """One row per client conversation with the Bedrock AgentCore runtime.

    ``agentcore_session_id`` carries Bedrock's runtimeSessionId as an opaque
    text value so format changes never force a migration. UNIQUE(client_id,
    agentcore_session_id) guards against duplicate-session rows under
    concurrent creation for the same client.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "agentcore_session_id",
            name="agent_sessions_client_id_agentcore_session_id_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Optional planning-mode pin. NULL means the session is unpinned — either
    # onboarding (client has no itineraries yet) or general Q&A (agent queries
    # across all the client's itineraries). ON DELETE SET NULL keeps the
    # session row alive if the referenced itinerary is removed.
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="SET NULL"),
        nullable=True,
    )
    agentcore_session_id: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    seeded_opener: Mapped[str | None] = mapped_column(nullable=True)
    # Which conversation this session is: the client-facing thread
    # ('traveler', default) or a private advisor workspace ('advisor'). Reuse
    # is keyed per (client_id, audience); a traveler actor is gated to
    # 'traveler' in open_or_reuse_session. See 0018.
    audience: Mapped[SessionAudience] = mapped_column(
        session_audience_enum,
        nullable=False,
        server_default=text("'traveler'"),
    )
    # A short label for the session — set explicitly (advisor rename) or
    # auto-derived from the first user message. NULL until the first turn.
    title: Mapped[str | None] = mapped_column(nullable=True)
    # Soft-archive marker: a non-NULL value hides the session from the list and
    # excludes it from reuse, without deleting its turns (0036).
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AgentTurn(Base):
    """Append-only conversation log for a session.

    ``content`` stores what the client saw post-stream so Command Center
    replays match the user experience. ``retried`` counts silent retries
    per turn (S04 slice verification reads this). ``first_token_ms`` is
    null when retries exhaust before any token streams.
    """

    __tablename__ = "agent_turns"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "turn_index",
            name="agent_turns_session_id_turn_index_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[TurnRole] = mapped_column(turn_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    model: Mapped[str | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_kind: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None] = mapped_column(nullable=True)
    retried: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    error_reason: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
