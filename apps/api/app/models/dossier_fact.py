from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class FactSourceKind(str, enum.Enum):
    """Mirrors public.fact_source_kind from migration 0011."""

    advisor = "advisor"
    agent_inferred = "agent_inferred"
    traveler_told = "traveler_told"
    scraper = "scraper"


class DossierFactKind(str, enum.Enum):
    """Mirrors public.dossier_fact_kind from migration 0011."""

    passion = "passion"
    motivation = "motivation"
    travel_history = "travel_history"
    trigger = "trigger"
    constraint = "constraint"
    deal_breaker = "deal_breaker"
    dream_signal = "dream_signal"
    party = "party"
    preference = "preference"
    other = "other"


fact_source_kind_enum = SAEnum(
    FactSourceKind,
    name="fact_source_kind",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

dossier_fact_kind_enum = SAEnum(
    DossierFactKind,
    name="dossier_fact_kind",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class DossierFact(Base):
    """Per-fact row of private internal knowledge.

    Two source_kinds are valid (CHECK-constrained DB-side):
    ``advisor`` (manually entered in command center) and
    ``agent_inferred`` (recorded by the agent during a turn). Both must
    NEVER be revealed verbatim to the traveler.
    """

    __tablename__ = "dossier_facts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sql_text("gen_random_uuid()"),
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[DossierFactKind] = mapped_column(
        dossier_fact_kind_enum, nullable=False
    )
    text: Mapped[str] = mapped_column(nullable=False)
    source_kind: Mapped[FactSourceKind] = mapped_column(
        fact_source_kind_enum, nullable=False
    )
    source_ref: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sql_text("'{}'::jsonb"),
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redacted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    redacted_reason: Mapped[str | None] = mapped_column(nullable=True)
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
