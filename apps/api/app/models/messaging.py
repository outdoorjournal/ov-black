"""ORM models for the unified human messaging substrate (M006/PS7).

Schema is owned by ``supabase/migrations/0037_messaging_threads.sql`` (D003) —
these classes are a read/write surface only, never used to emit DDL. Per Q13 =
UNIFY, one ``threads`` / ``messages`` / ``thread_participants`` store carries the
human channel now and (PS8) Artemis-in-thread turns later; the disclosure
boundary is the thread's ``audience`` column (the reused ``session_audience``
enum from 0018), NOT the message author.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.agent import SessionAudience


class ThreadKind(str, enum.Enum):
    """Mirrors public.thread_kind (0037): an Artemis engine thread vs a human channel."""

    ai_session = "ai_session"
    human = "human"


class ThreadActorKind(str, enum.Enum):
    """Mirrors public.thread_actor_kind (0037).

    Who authored a message / who participates. ``artemis`` is the explicit AI
    attribution (PS8); ``system`` is for automated notices. Shared by
    ``messages.author_kind`` and ``thread_participants.actor_kind``.
    """

    traveler = "traveler"
    advisor = "advisor"
    artemis = "artemis"
    system = "system"


# Postgres owns both types (D003/D020); SQLAlchemy binds with create_type=False.
thread_kind_enum = PGEnum(
    ThreadKind,
    name="thread_kind",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)
thread_actor_kind_enum = PGEnum(
    ThreadActorKind,
    name="thread_actor_kind",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)
# The disclosure boundary reuses 0018's session_audience type. Bind a fresh
# PGEnum by name (Postgres owns the type, create_type=False) rather than import
# the agent-model instance — the cross-module value import created a mypy
# import-cycle [has-type] on this module.
session_audience_enum = PGEnum(
    SessionAudience,
    name="session_audience",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Thread(Base):
    """A conversation container. ``audience`` is the disclosure boundary.

    ``itinerary_id`` NULL = basecamp scope (you ↔ advisor); non-null = that
    trip's thread (you ↔ advisor ↔ party). A human thread is get-or-created
    per ``(client_id, itinerary_id, audience)`` via the two partial unique
    indexes in 0037.
    """

    __tablename__ = "threads"

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
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[ThreadKind] = mapped_column(thread_kind_enum, nullable=False)
    # Reuse the 0018 session_audience enum (Postgres owns the type; create_type
    # already False on the shared binding). The thread's audience IS the
    # disclosure boundary that makes the PS8 invariant fall out.
    audience: Mapped[SessionAudience] = mapped_column(
        session_audience_enum,
        nullable=False,
        server_default=text("'traveler'"),
    )
    title: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Message(Base):
    """One human-visible message. ``author_id`` NULL for artemis/system.

    ``proposed_node_id`` is the PS8 hook for a card proposal flowing to the one
    graph — unused by human turns. ``removed_at`` is a soft-delete marker;
    ``edited_at`` marks an in-place edit.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_kind: Mapped[ThreadActorKind] = mapped_column(thread_actor_kind_enum, nullable=False)
    # FK to auth.users(id) is enforced DB-side (0037); auth.users is not a
    # mapped table, so no ORM ForeignKey here (mirrors the Client model).
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(nullable=False)
    proposed_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ThreadParticipant(Base):
    """Explicit thread membership. OV's disclosure rules must know exactly who
    can see a thread, so participation is EXPLICIT (not implicit-by-authorship).

    Artemis is not a standing participant in a human thread — it is summoned
    per-turn (PS8) — so ``actor_id`` is NOT NULL and the PK is
    ``(thread_id, actor_id)``.
    """

    __tablename__ = "thread_participants"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threads.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # FK to auth.users(id) is enforced DB-side (0037) — no ORM ForeignKey.
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    actor_kind: Mapped[ThreadActorKind] = mapped_column(thread_actor_kind_enum, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
