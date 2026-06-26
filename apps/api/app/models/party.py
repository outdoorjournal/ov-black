"""Party / Traveler / NodeParty models — TravelGraph Phase 1 (0014).

A party is a sub-group inside an itinerary's travel party (e.g. "the kids",
"adults"). Each party has its own timeline projection over the merged
itinerary graph; nodes opt into parties via ``node_parties``. The default
behavior in Phase 2 is a single synthetic "all" party per itinerary so
existing code paths keep working before per-party flows land.

Schema is owned by ``supabase/migrations/0014_travelgraph_schema_spine.sql``
— these classes are a read/write surface only.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class PartyMemberActor(str, enum.Enum):
    """Mirrors the public.party_member_actor enum from 0019.

    Who authored / last touched a member — party data is a three-way
    collaboration between the advisor, the traveler (self-service), and the
    agent (recorded mid-conversation).
    """

    advisor = "advisor"
    traveler = "traveler"
    agent = "agent"


# Postgres owns the type (D003/D020); SQLAlchemy binds with create_type=False.
party_member_actor_enum = PGEnum(
    PartyMemberActor,
    name="party_member_actor",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Party(Base):
    """A travel sub-group within an itinerary."""

    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    member_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Traveler(Base):
    """An individual traveler belonging to a Party."""

    __tablename__ = "travelers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The durable member this per-trip row represents (0019). Nullable so legacy
    # rows + ad-hoc travelers without a saved member still work; on delete the
    # link clears rather than dropping trip history.
    party_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("party_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PartyMember(Base):
    """A durable, household-scoped traveler identity (0019 — M003/V1).

    Owned by a ``client`` (the account/household), reused across every itinerary
    that client takes — "remember previous travelers". Carries the
    identity-bearing fields; per-trip participation is the ``travelers`` row that
    references this member via ``party_member_id``. Authored collaboratively by
    advisor / traveler / agent (see ``created_by_actor`` / ``updated_by_actor``).
    """

    __tablename__ = "party_members"

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
    full_name: Mapped[str] = mapped_column(nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str | None] = mapped_column(nullable=True)
    dietary: Mapped[str | None] = mapped_column(nullable=True)
    medical: Mapped[str | None] = mapped_column(nullable=True)
    mobility: Mapped[str | None] = mapped_column(nullable=True)
    loyalty_programs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    emergency_contact: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    relationship_to_primary: Mapped[str | None] = mapped_column(nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    notes: Mapped[str | None] = mapped_column(nullable=True)
    created_by_actor: Mapped[PartyMemberActor] = mapped_column(
        party_member_actor_enum, nullable=False
    )
    updated_by_actor: Mapped[PartyMemberActor] = mapped_column(
        party_member_actor_enum, nullable=False
    )
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NodeParty(Base):
    """Many-to-many: which parties' timelines contain this node."""

    __tablename__ = "node_parties"

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    party_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parties.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
