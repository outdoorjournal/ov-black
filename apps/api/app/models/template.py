"""Card-template registry — TravelGraph Phase 4 (0015).

A template is a reusable card / sub-graph an advisor can copy into any
client itinerary. Time is stored as offsets from a "trip start" anchor;
the instantiation operation receives a concrete ``trip_start_at`` and
materializes absolute ``tstzrange`` values on the new nodes.

Every instantiated node remembers ``template_id`` + ``template_node_id``
+ ``template_version`` so a future drift detector can flag "this
template has been edited since you used it" without comparing every
field. The new columns live on ``public.nodes`` (see 0015 §4) and are
already present on the ``Node`` ORM class — this module owns the
template-side classes only.

Schema is owned by ``supabase/migrations/0015_card_templates.sql``;
these classes are a read/write surface only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.itinerary import (
    EdgeType,
    NodeRole,
    NodeType,
    edge_type_enum,
    node_role_enum,
    node_type_enum,
)


class CardTemplate(Base):
    """A reusable card or sub-graph in the operator's deck."""

    __tablename__ = "card_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(nullable=False, unique=True)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(
        nullable=False, server_default=text("''")
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    owner_advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TemplateNode(Base):
    """One node inside a CardTemplate's subgraph.

    Mirrors ``Node`` for every field the renderer / agent reads but
    replaces ``starts_at`` (tstzrange) with ``starts_at_offset_minutes``
    so the same template can be instantiated against any trip start.
    Geometry (location/route) lives only in ``metadata`` for now and
    promotes to first-class columns when geoalchemy2 lands.
    """

    __tablename__ = "template_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("card_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    attached_to_template_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    type: Mapped[NodeType] = mapped_column(node_type_enum, nullable=False)
    role: Mapped[NodeRole | None] = mapped_column(node_role_enum, nullable=True)
    title: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    starts_at_offset_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    altitude_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_selected_alt: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
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


class TemplateEdge(Base):
    """A typed edge inside a CardTemplate's subgraph."""

    __tablename__ = "template_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("card_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_template_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_template_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[EdgeType] = mapped_column(edge_type_enum, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
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
