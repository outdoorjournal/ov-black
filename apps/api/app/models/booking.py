"""Node-offer + booking ORM models (M005 / I3, migration 0025).

Schema is owned by ``supabase/migrations/0025_bookings.sql`` (D003) — these
classes are a read/write surface only and never emit DDL.

Two structured tables carry booking + repriceable-offer state OUT of node
``metadata`` (D024, mirrors D005):

- :class:`NodeOffer` — a transient, time-boxed supplier quote attached while a
  node is pre-booking. A Duffel flight offer is a price HELD until ``expires_at``,
  not a stable listing; ``refreshed_from_offer_id`` chains a re-price to the
  quote it replaced so the history is queryable.
- :class:`Booking` — the committed booking record: the amount actually charged
  (the re-priced/held amount), the offer it was booked from, the covering invoice
  LINE it was paid by (the money-gate link), the supplier confirmation # set at
  ``confirmed``, and the logged ``override_unpaid`` D-PAY flag. One live booking
  per node (the ``bookings_one_per_node`` unique index).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.invoice import RefundStatus, refund_status_enum


class NodeOffer(Base):
    """A time-boxed, repriceable supplier quote attached to a node."""

    __tablename__ = "node_offers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'duffel' (live re-price), 'snapshot' (frozen from B4 cost), or 'manual'.
    source: Mapped[str] = mapped_column(nullable=False)
    # The provider's own offer id (a Duffel offer id) so a re-price can re-fetch
    # it; null for snapshot/manual quotes.
    source_offer_id: Mapped[str | None] = mapped_column(nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    priced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # When the held price lapses; null = no expiry (snapshot/manual).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The prior offer this quote re-prices (refresh lineage); null for the first.
    refreshed_from_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("node_offers.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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


class Booking(Base):
    """The committed booking record for a node (one live per node)."""

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The offer this was booked from (flights re-price first); null for nodes
    # booked at their static B4 cost.
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("node_offers.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The invoice line that covers this booking — the money-gate link.
    invoice_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoice_line_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    # PNR / order id, recorded when the node advances booked → confirmed.
    supplier_ref: Mapped[str | None] = mapped_column(nullable=True)
    change_cancel_terms: Mapped[str | None] = mapped_column(nullable=True)
    # D-PAY override: booked against a merely *issued* (not *paid*) line. Logged.
    override_unpaid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    booked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    booked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ── Cancel + refund (0028) — null until an advisor cancels this booking ──
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(nullable=True)
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    refund_currency: Mapped[str | None] = mapped_column(nullable=True)
    refund_status: Mapped[RefundStatus | None] = mapped_column(refund_status_enum, nullable=True)
    # OUR cross-ref key for the refund (= processor order id). Sensitive — never
    # logged, mirroring payments.gateway_reference.
    refund_gateway_ref: Mapped[str | None] = mapped_column(nullable=True)
    # Two-way link to the refund Payment row (0024 payments, status='refunded').
    refund_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
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
