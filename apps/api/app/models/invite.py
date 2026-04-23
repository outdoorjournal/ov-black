from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.profile import UserRole, user_role_enum


class Invite(Base):
    """Single-use invite code that gates magic-link issuance.

    All mutations flow through the service_role-backed admin path (RLS denies
    everyone else). ``consumed_at`` is set atomically alongside magic-link
    issuance — see T05. ``cancelled_at`` and ``superseded_at`` (0007) record
    the post-creation lifecycle: a resend supersedes the prior row and inserts
    a new one; a cancel stamps the active row. An invite is "active" iff all
    three timestamps are NULL.
    """

    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(primary_key=True)
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    email: Mapped[str | None] = mapped_column(nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
