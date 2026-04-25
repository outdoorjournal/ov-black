from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer

from app.models import Base
from app.models.client import (
    ContactChannel,
    GroupType,
    contact_channel_enum,
    group_type_enum,
)


class Dossier(Base):
    """1:1 with ``clients`` — typed core columns only (long-tail moved to dossier_facts).

    The dossier holds private internal knowledge: structured signals seeded by
    the advisor at onboarding (group type, children ages, contact channel,
    party notes, net worth). Long-tail facts (passions, motivations, etc.) and
    agent inferences live in ``dossier_facts``; external research lives in
    ``osint_facts``; traveler self-expression lives in ``profile_facts``.

    ``authored_by`` is the advisor who wrote the dossier — kept explicit so
    future co-advising or hand-off flows do not require a migration.
    """

    __tablename__ = "dossiers"

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
