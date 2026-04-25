from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ContactKind(str, enum.Enum):
    """Mirrors the public.contact_kind Postgres enum from 0013_client_contacts.sql."""

    phone_cell = "phone_cell"
    phone_home = "phone_home"
    phone_work = "phone_work"
    whatsapp = "whatsapp"
    signal = "signal"
    telegram = "telegram"
    imessage = "imessage"
    instagram = "instagram"
    linkedin = "linkedin"
    x = "x"
    facebook = "facebook"
    wechat = "wechat"
    other = "other"


# Reuse the Postgres-side enum type — SQLAlchemy must not CREATE TYPE (D003).
contact_kind_enum = PGEnum(
    ContactKind,
    name="contact_kind",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class ClientContact(Base):
    """A single contact method (phone / messenger / social) for a client."""

    __tablename__ = "client_contacts"

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
    kind: Mapped[ContactKind] = mapped_column(contact_kind_enum, nullable=False)
    value: Mapped[str] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
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
