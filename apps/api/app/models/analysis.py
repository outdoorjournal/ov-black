"""ORM models for async Analyze (TravelGraph Phase 5 / B5).

Hand-aligned to ``supabase/migrations/0017_async_analyze.sql`` — read/write
surface only, never used to emit DDL (D003). Two tables: :class:`Analysis`
(one run with a status state machine + the agent-readable aggregate ``result``)
and :class:`AnalysisFinding` (the append-only list of individual problems).

Analyze is read-only over the graph — these tables never reference back into
``nodes`` as a write target; ``AnalysisFinding.node_id`` is a nullable, ON
DELETE SET NULL pointer so a finding survives a later node purge.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AnalysisStatus(str, enum.Enum):
    """Mirrors the public.analysis_status Postgres enum (0017).

    Run state machine: ``queued`` -> ``running`` -> ``completed``, with
    ``failed`` / ``cancelled`` as terminal side-exits. Terminal states are
    immutable — the background runner checks status before each commit.
    """

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AnalysisDepth(str, enum.Enum):
    """Mirrors the public.analysis_depth Postgres enum (0017).

    Explicitly chosen by the caller, never inferred (D-ANALYZE). ``shallow`` =
    structural only (no external calls); ``standard`` = physical-feasibility
    envelope (haversine drive-times). ``deep`` (live external data) is deferred
    for the MVP — the runner downgrades a ``deep`` request to ``standard``.
    """

    shallow = "shallow"
    standard = "standard"
    deep = "deep"


class FindingSeverity(str, enum.Enum):
    """Mirrors the public.finding_severity Postgres enum (0017).

    Ordered ``info`` < ``suggest`` < ``warn`` < ``block``. ``block`` is a
    physical impossibility — Fill must not propose candidates that don't
    resolve it.
    """

    info = "info"
    suggest = "suggest"
    warn = "warn"
    block = "block"


# Reuse the Postgres-side enum types — the migration owns CREATE TYPE, so
# create_type=False is load-bearing (mirrors models/itinerary.py + D020).
analysis_status_enum: PGEnum = PGEnum(
    AnalysisStatus,
    name="analysis_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

analysis_depth_enum: PGEnum = PGEnum(
    AnalysisDepth,
    name="analysis_depth",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

finding_severity_enum: PGEnum = PGEnum(
    FindingSeverity,
    name="finding_severity",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Analysis(Base):
    """One Analyze run over an itinerary graph."""

    __tablename__ = "analyses"

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
    status: Mapped[AnalysisStatus] = mapped_column(
        analysis_status_enum,
        nullable=False,
        server_default=text("'queued'::public.analysis_status"),
    )
    depth: Mapped[AnalysisDepth] = mapped_column(
        analysis_depth_enum,
        nullable=False,
        server_default=text("'standard'::public.analysis_depth"),
    )
    scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    inputs_hash: Mapped[str | None] = mapped_column(nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    requested_kind: Mapped[str] = mapped_column(
        nullable=False,
        server_default=text("'user'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(nullable=True)
    external_calls: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    error_detail: Mapped[str | None] = mapped_column(nullable=True)
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


class AnalysisFinding(Base):
    """One problem surfaced by an Analyze run. Append-only."""

    __tablename__ = "analysis_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        finding_severity_enum,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(nullable=False)
    message: Mapped[str] = mapped_column(nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    suggested_fix: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
