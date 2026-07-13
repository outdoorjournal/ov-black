from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ContactChannel(str, enum.Enum):
    """Mirrors the public.contact_channel Postgres enum from 0003_clients_dossiers.sql."""

    email = "email"
    sms = "sms"
    whatsapp = "whatsapp"
    phone = "phone"


# Reuse the Postgres-side enum types — SQLAlchemy must not try to CREATE TYPE,
# the migration owns that. native_enum=True + create_type=False enforces this.
contact_channel_enum: SAEnum = SAEnum(
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
    the client). ``auth_user_id`` is the client's own ``auth.users`` id,
    backfilled on their first magic-link login (see
    ``resolve_client_for_auth_user``). NULL means the client hasn't signed in
    yet.

    ``invited_at`` is stamped when the welcome sign-in link is first issued
    (NULL = never invited). Together with ``auth_user_id`` it yields the
    three-state access status the advisor UI renders: ``uninvited`` (created,
    never notified) → ``pending`` (invited, awaiting first login) → ``active``.
    """

    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # FK to auth.users(id) is enforced DB-side (migration 0003). SQLAlchemy
    # does not model cross-schema FKs here — ``auth`` is not part of our
    # declarative metadata, matching the Profile convention.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    # Stamped on first magic-link login (when auth_user_id is backfilled).
    # NULL == hasn't signed in yet.
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Stamped when the welcome sign-in link is first issued. NULL == the client
    # was created silently and never invited → the UI renders "uninvited".
    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    full_name: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
    # Traveler logistics (0048). All nullable — unknown until the advisor or the
    # agent records them. ``address`` is free text (international addresses are
    # irregular); ``favorite_airport`` is a 3-letter IATA code; and
    # ``preferred_currency`` is the ISO 4217 the traveler wants money shown in,
    # which drives read-time FX conversion of totals and the agent's quoting.
    address: Mapped[str | None] = mapped_column(nullable=True)
    favorite_airport: Mapped[str | None] = mapped_column(nullable=True)
    preferred_currency: Mapped[str | None] = mapped_column(nullable=True)
    # Structured billing-address parts (0051) — `address` above is the street
    # line; these complete it for the pay form + Braintree billing. All nullable.
    city: Mapped[str | None] = mapped_column(nullable=True)
    region: Mapped[str | None] = mapped_column(nullable=True)
    postal_code: Mapped[str | None] = mapped_column(nullable=True)
    country_code: Mapped[str | None] = mapped_column(nullable=True)
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
