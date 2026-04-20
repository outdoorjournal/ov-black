from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class GroupType(str, enum.Enum):
    """Mirrors the public.group_type Postgres enum from 0003_clients_voodoo_dolls.sql."""

    solo = "solo"
    couple = "couple"
    family = "family"
    friends = "friends"
    multigen = "multigen"
    corporate = "corporate"


class ContactChannel(str, enum.Enum):
    """Mirrors the public.contact_channel Postgres enum from 0003_clients_voodoo_dolls.sql."""

    email = "email"
    sms = "sms"
    whatsapp = "whatsapp"
    phone = "phone"


# Reuse the Postgres-side enum types — SQLAlchemy must not try to CREATE TYPE,
# the migration owns that. native_enum=True + create_type=False enforces this.
group_type_enum = SAEnum(
    GroupType,
    name="group_type",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

contact_channel_enum = SAEnum(
    ContactChannel,
    name="contact_channel",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Client(Base):
    """Advisor-owned client record.

    ``owner_id`` is the advisor's ``auth.users`` id (the advisor who created
    the client). ``auth_user_id`` is the client's own ``auth.users`` id once
    they redeem the invite — populated by a later slice.
    """

    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # FK to auth.users(id) is enforced DB-side (migration 0003). SQLAlchemy
    # does not model cross-schema FKs here — ``auth`` is not part of our
    # declarative metadata, matching the Profile/Invite convention.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    full_name: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
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
