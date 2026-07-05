from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, func, text
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


class CostKind(str, enum.Enum):
    """Mirrors the public.cost_kind Postgres enum (0016).

    Whether a node's ``cost_amount`` is quoted per traveler (``per_person``)
    or as a single total for the node (``total``). Inventory providers that
    quote a whole-booking price (Duffel offer total, Ratehawk stay total) map
    to ``total``; OV-style per-person experiences map to ``per_person``.
    """

    per_person = "per_person"
    total = "total"


class EdgeType(str, enum.Enum):
    """Mirrors the public.edge_type Postgres enum."""

    follows = "follows"
    alternative_to = "alternative_to"
    connected_by = "connected_by"
    requires = "requires"
    grouped_with = "grouped_with"


class ItineraryStatus(str, enum.Enum):
    """Mirrors the public.itinerary_status Postgres enum (0006, `proposed` 0039).

    Lifecycle: ``draft`` (advisor building) → ``proposed`` (advisor finished and
    handed the plan to the traveler for review, freezing the build) → ``approved``
    (the traveler has approved — the itinerary-level ``approved`` is *derived*:
    it is set once every remaining ``proposed`` node has been actioned). The
    whole itinerary follows the same ``proposed → approved`` arc as its nodes.
    """

    draft = "draft"
    proposed = "proposed"
    approved = "approved"


class ForkStatus(str, enum.Enum):
    """Mirrors the public.fork_status Postgres enum (0021, G2).

    The reconcile lifecycle of a fork: ``open`` (a fresh fork, still diverging),
    ``reconciled`` (its accepted changes were folded back into the baseline),
    ``abandoned`` (discarded without folding back). NULL on a baseline itinerary.
    """

    open = "open"
    reconciled = "reconciled"
    abandoned = "abandoned"


class ItineraryTimingKind(str, enum.Enum):
    """Mirrors the public.itinerary_timing_kind Postgres enum (0033).

    How to read an itinerary's timing fields:
    - ``exact``: ``date_start``/``date_end`` are the fixed trip.
    - ``window``: ``date_start``/``date_end`` bound the acceptable window and
      ``duration_nights`` is the target length somewhere inside it
      ("~7 nights within Jun-Aug").
    - ``flexible``: no dates chosen yet; ``timing_note`` carries the intent.

    NULL on legacy rows and freshly auto-created "Concierge draft" itineraries
    that haven't been through the builder's first-run intake.
    """

    exact = "exact"
    window = "window"
    flexible = "flexible"


# Reuse the Postgres-side enum types — SQLAlchemy must not try to CREATE TYPE,
# the migration owns that. postgresql.ENUM surfaces create_type as a real
# attribute (the generic sqlalchemy.Enum silently drops it), so tests can
# regression-guard D003 directly. create_type=False is load-bearing here.
node_type_enum: PGEnum = PGEnum(
    NodeType,
    name="node_type",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

node_status_enum: PGEnum = PGEnum(
    NodeStatus,
    name="node_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

edge_type_enum: PGEnum = PGEnum(
    EdgeType,
    name="edge_type",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

cost_kind_enum: PGEnum = PGEnum(
    CostKind,
    name="cost_kind",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

node_role_enum: PGEnum = PGEnum(
    NodeRole,
    name="node_role",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

itinerary_status_enum: PGEnum = PGEnum(
    ItineraryStatus,
    name="itinerary_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

fork_status_enum: PGEnum = PGEnum(
    ForkStatus,
    name="fork_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

itinerary_timing_kind_enum: PGEnum = PGEnum(
    ItineraryTimingKind,
    name="itinerary_timing_kind",
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
    # 0039 — ADV-10 propose step. Siblings of approved_by/at: set when the advisor
    # *proposes* the plan to the traveler (status draft → proposed), cleared on
    # reopen (proposed → draft). NULL until first proposed.
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    proposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 0021 — fork lineage (G2). ``forked_from_id`` points at the baseline this
    # itinerary was cloned from (NULL on a normal itinerary); ``fork_status``
    # tracks the reconcile lifecycle and is NULL unless this row is a fork.
    forked_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="SET NULL"),
        nullable=True,
    )
    fork_status: Mapped[ForkStatus | None] = mapped_column(fork_status_enum, nullable=True)
    # 0022 — reconcile request (G3). A traveler/agent can't merge a fork; they
    # stamp ``reconcile_requested_at`` (+ an optional note) to ask staff to. NULL
    # until requested, cleared on reconcile/abandon. Both live only on a fork row.
    reconcile_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconcile_request_note: Mapped[str | None] = mapped_column(nullable=True)
    # 0033 — first-class trip brief + timing. ``brief`` is the free-text goal
    # ("sailing in Greece with my family"); the timing fields model when, from
    # exact dates through a fuzzy-but-bounded window to fully flexible. See
    # ``ItineraryTimingKind`` for how ``timing_kind`` governs date_start/date_end
    # + duration_nights, and ``timing_note`` for free-text constraints ("not
    # August", "back by a Sunday"). All NULL until the builder's first-run intake.
    brief: Mapped[str | None] = mapped_column(nullable=True)
    timing_kind: Mapped[ItineraryTimingKind | None] = mapped_column(
        itinerary_timing_kind_enum,
        nullable=True,
    )
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timing_note: Mapped[str | None] = mapped_column(nullable=True)
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
    metadata_: Mapped[dict[str, Any]] = mapped_column(
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
    # 0015 — template lineage. ``template_id`` is FK with ON DELETE SET NULL
    # so a node survives template purges. ``template_node_id`` points at the
    # specific template_node row that was the source; ``template_version`` is
    # the snapshot of card_templates.version at instantiation, used for drift
    # detection without comparing every field.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("card_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    template_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0016 — first-class node cost (D-COST). Promotes a bookable node's price
    # from free-text metadata to queryable columns so M005 invoicing + the
    # money gate can SUM(cost). ``cost_amount`` (native major units) and
    # ``cost_currency`` (ISO 4217) travel together — the DB CHECK
    # ``nodes_cost_amount_currency_together`` enforces both-or-neither.
    # ``cost_kind`` is independent. A flight's amount is a repriceable quote
    # (D024); the transient offer history lives in ``node_offers`` (M005).
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(nullable=True)
    cost_kind: Mapped[CostKind | None] = mapped_column(cost_kind_enum, nullable=True)
    # 0021 — fork lineage (G2). The baseline node this one was copied from when its
    # itinerary was forked; NULL for a hand-built / inventory-sourced node. ON
    # DELETE SET NULL so editing the baseline node doesn't cascade into the fork.
    forked_from_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
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
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
