from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer

from app.models import Base
from app.models.client import (
    ContactChannel,
    GroupType,
    contact_channel_enum,
    group_type_enum,
)


class VoodooDoll(Base):
    """1:1 with ``clients`` — typed core columns + JSONB long-tail fields.

    Typed columns capture stable signals S04's agent will ground on; JSONB
    columns hold the evolving long-tail (passions, motivations, travel
    history, …). ``authored_by`` is the advisor who wrote the doll — in S03
    always equals ``clients.owner_id`` but kept explicit so future co-advising
    or hand-off flows do not require a migration.
    """

    __tablename__ = "voodoo_dolls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # FK to auth.users(id) is enforced DB-side (migration 0003); ``auth`` is
    # not part of SQLAlchemy metadata, matching the Profile/Client convention.
    authored_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    contact_preference: Mapped[ContactChannel] = mapped_column(
        contact_channel_enum,
        nullable=False,
    )
    group_type: Mapped[GroupType] = mapped_column(group_type_enum, nullable=False)
    children_ages: Mapped[list[int]] = mapped_column(
        ARRAY(Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    )
    travel_party_notes: Mapped[str] = mapped_column(
        nullable=False,
        server_default=text("''"),
    )
    estimated_net_worth_usd: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    passions: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    motivations: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    travel_history: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    triggers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    constraints: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    deal_breakers: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    dream_trip_signals: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    osint_notes: Mapped[dict] = mapped_column(
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
