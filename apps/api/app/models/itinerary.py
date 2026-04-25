from __future__ import annotations

import enum
import uuid
from datetime import datetime

from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class NodeType(str, enum.Enum):
    """Mirrors the public.node_type Postgres enum.

    0002_itinerary_graph.sql introduced the original 8 values; 0014 added
    the per-mode transit kinds (subway/train/drive/walk/boat) and `waiting`
    so each card kind carries its own signature detail per the cards style
    guide. `transit` and `destination` remain valid for legacy rows but
    Phase 2+ writes prefer the granular kinds.
    """

    destination = "destination"
    flight = "flight"
    hotel = "hotel"
    experience = "experience"
    meal = "meal"
    transit = "transit"
    free_time = "free_time"
    note = "note"
    subway = "subway"
    train = "train"
    drive = "drive"
    walk = "walk"
    boat = "boat"
    waiting = "waiting"


class NodeRole(str, enum.Enum):
    """Mirrors the public.node_role Postgres enum from 0014.

    Graph-structural axis orthogonal to NodeType. Linearization skips rows
    where role is non-null; renderers use them as headers / sync points.
    """

    destination = "destination"
    terminus = "terminus"


class NodeStatus(str, enum.Enum):
    """Mirrors the public.node_status Postgres enum."""

    idea = "idea"
    proposed = "proposed"
    approved = "approved"
    booked = "booked"
    confirmed = "confirmed"
    discarded = "discarded"


class EdgeType(str, enum.Enum):
    """Mirrors the public.edge_type Postgres enum."""

    follows = "follows"
    alternative_to = "alternative_to"
    connected_by = "connected_by"
    requires = "requires"
    grouped_with = "grouped_with"


class ItineraryStatus(str, enum.Enum):
    """Mirrors the public.itinerary_status Postgres enum (0006)."""

    draft = "draft"
    approved = "approved"


# Reuse the Postgres-side enum types — SQLAlchemy must not try to CREATE TYPE,
# the migration owns that. postgresql.ENUM surfaces create_type as a real
# attribute (the generic sqlalchemy.Enum silently drops it), so tests can
# regression-guard D003 directly. create_type=False is load-bearing here.
node_type_enum = PGEnum(
    NodeType,
    name="node_type",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

node_status_enum = PGEnum(
    NodeStatus,
    name="node_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

edge_type_enum = PGEnum(
    EdgeType,
    name="edge_type",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

node_role_enum = PGEnum(
    NodeRole,
    name="node_role",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

itinerary_status_enum = PGEnum(
    ItineraryStatus,
    name="itinerary_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Itinerary(Base):
    """Top-level container for a client's trip graph."""

    __tablename__ = "itineraries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[ItineraryStatus] = mapped_column(
        itinerary_status_enum,
        nullable=False,
        default=ItineraryStatus.draft,
        server_default=text("'draft'::public.itinerary_status"),
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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


class Node(Base):
    """Item in an itinerary graph. Self-FK via parent_subgraph_id for subgraphs."""

    __tablename__ = "nodes"

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
    parent_subgraph_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    type: Mapped[NodeType] = mapped_column(node_type_enum, nullable=False)
    status: Mapped[NodeStatus] = mapped_column(
        node_status_enum,
        nullable=False,
        server_default=text("'idea'::public.node_status"),
    )
    title: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    source: Mapped[str | None] = mapped_column(nullable=True)
    source_id: Mapped[str | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    # 0014 — first-class temporal/spatial/structural columns. The
    # `location` and `route` PostGIS geography columns exist in the DB
    # (see 0014) but are intentionally omitted from this ORM until the
    # geoalchemy2 dependency lands; raw queries can still read/write them.
    starts_at: Mapped[Any | None] = mapped_column(TSTZRANGE, nullable=True)
    altitude_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_selected_alt: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )
    attached_to_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    role: Mapped[NodeRole | None] = mapped_column(node_role_enum, nullable=True)
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


class Edge(Base):
    """Typed relationship between two nodes in the same itinerary."""

    __tablename__ = "edges"

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
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[EdgeType] = mapped_column(edge_type_enum, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NodeHistory(Base):
    """Append-only audit log for node mutations.

    Written by the service layer in the same transaction as the mutation
    (NOT via trigger — see S02 research Decision). ``before`` is null on
    insert; ``after`` is null on delete.
    """

    __tablename__ = "node_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    op: Mapped[str] = mapped_column(nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None] = mapped_column(nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EdgeHistory(Base):
    """Append-only audit log for edge mutations. Same shape as NodeHistory."""

    __tablename__ = "edge_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    edge_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    itinerary_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    op: Mapped[str] = mapped_column(nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(nullable=False)
    actor_id: Mapped[str | None] = mapped_column(nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
