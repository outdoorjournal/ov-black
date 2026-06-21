from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class UserRole(str, enum.Enum):
    """Mirrors the public.user_role Postgres enum from 0001_init.sql."""

    advisor = "advisor"
    client = "client"


# Reuse the Postgres-side enum type — SQLAlchemy must not try to CREATE TYPE,
# the migration owns that. native_enum=True + create_type=False enforces this.
user_role_enum = SAEnum(
    UserRole,
    name="user_role",
    schema="public",
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Profile(Base):
    """1:1 with auth.users — carries the application role for a user."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
