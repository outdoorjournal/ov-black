from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.dossier_fact import FactSourceKind, fact_source_kind_enum


class ProfileFactKind(str, enum.Enum):
    """Mirrors public.profile_fact_kind from migration 0011."""

    passion = "passion"
    motivation = "motivation"
    travel_history = "travel_history"
    trigger = "trigger"
    constraint = "constraint"
    deal_breaker = "deal_breaker"
    dream_signal = "dream_signal"
    preference = "preference"
    aspiration = "aspiration"
    other = "other"


profile_fact_kind_enum = SAEnum(
    ProfileFactKind,
    name="profile_fact_kind",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class ProfileFact(Base):
    """Per-fact row of traveler self-expression.

    Two source_kinds are valid (CHECK-constrained DB-side):
    ``traveler_told`` (the agent recorded it after the traveler said it)
    and ``advisor`` (the advisor manually attributed it on the traveler's
    behalf). The agent MAY reference profile facts naturally in
    conversation — this is the tier where "you mentioned …" is fair.
    """

    __tablename__ = "profile_facts"

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
    kind: Mapped[ProfileFactKind] = mapped_column(
        profile_fact_kind_enum, nullable=False
    )
    text: Mapped[str] = mapped_column(nullable=False)
    source_kind: Mapped[FactSourceKind] = mapped_column(
        fact_source_kind_enum, nullable=False
    )
    source_ref: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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
