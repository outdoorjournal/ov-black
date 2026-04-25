"""Onboarding-flow ORM rows (Basecamp opener bank)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class OnboardingOpener(Base):
    """One curated open-ended question used to seed a new client's first turn.

    The bank is small (handful of rows seeded by 0010_onboarding_openers.sql)
    and read-only via the API. ``weight`` is reserved for future weighted
    sampling; v1 uses uniform random selection over ``enabled = true`` rows.
    """

    __tablename__ = "onboarding_openers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    prompt: Mapped[str] = mapped_column(nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
