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

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


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
    attrs: Mapped[dict] = mapped_column(
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
    name: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_attrs: Mapped[dict] = mapped_column(
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
