"""Invoice + line-item ORM models (M005 / I1, migration 0023).

Schema is owned by ``supabase/migrations/0023_invoices.sql`` (D003) — these
classes are a read/write surface only and never emit DDL. An invoice is a small
LEDGER over an itinerary: its line items are *signed* entries (charges,
discounts, adjustments, taxes, fees, and append-only ``reversal`` voids), and
the invoice total is always Σ(line amounts) — there is no stored total, so the
ledger is the single source of truth the money gate (I3) reconciles against.

The ``payments`` model (I2) lives in this file too so the invoice/payment
surface stays in one module.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class InvoiceStatus(str, enum.Enum):
    """Mirrors the public.invoice_status Postgres enum (0023).

    ``draft`` (advisor assembling) → ``issued`` (sent, payable) → ``paid`` (a
    covering payment settled, I2); ``void`` is the terminal cancel.
    """

    draft = "draft"
    issued = "issued"
    paid = "paid"
    void = "void"


class PaymentStatus(str, enum.Enum):
    """Mirrors the public.payment_status Postgres enum (0024).

    ``refunded`` is future-proofing — I2 only writes ``succeeded`` / ``failed``.
    """

    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class InvoiceLineKind(str, enum.Enum):
    """Mirrors the public.invoice_line_kind Postgres enum (0023).

    What a (signed) line represents. ``charge``/``tax``/``fee`` are normally
    positive; ``discount``/``adjustment``/``reversal`` are normally negative.
    ``reversal`` is the journal-entry void — it negates the line it points at
    via ``reverses_line_item_id``.
    """

    charge = "charge"
    discount = "discount"
    adjustment = "adjustment"
    tax = "tax"
    fee = "fee"
    reversal = "reversal"


# Reuse the Postgres-side enum types (D020) — create_type=False so SQLAlchemy
# never emits CREATE TYPE; the migration owns the type.
invoice_status_enum: PGEnum = PGEnum(
    InvoiceStatus,
    name="invoice_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

invoice_line_kind_enum: PGEnum = PGEnum(
    InvoiceLineKind,
    name="invoice_line_kind",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

payment_status_enum: PGEnum = PGEnum(
    PaymentStatus,
    name="payment_status",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class Invoice(Base):
    """One of an itinerary's N invoices (a deposit, a balance, …)."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    status: Mapped[InvoiceStatus] = mapped_column(
        invoice_status_enum,
        nullable=False,
        default=InvoiceStatus.draft,
        server_default=text("'draft'::public.invoice_status"),
    )
    currency: Mapped[str] = mapped_column(nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
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


class InvoiceLineItem(Base):
    """A signed ledger entry on an invoice (charge / discount / … / reversal)."""

    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[InvoiceLineKind] = mapped_column(
        invoice_line_kind_enum,
        nullable=False,
        default=InvoiceLineKind.charge,
        server_default=text("'charge'::public.invoice_line_kind"),
    )
    description: Mapped[str] = mapped_column(nullable=False, server_default=text("''"))
    # Signed: charges/taxes/fees > 0; discounts/adjustments/reversals < 0.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    # For a ``reversal`` line: the original line it voids (else NULL).
    reverses_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoice_line_items.id", ondelete="SET NULL"),
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Payment(Base):
    """A charge attempt against an invoice (M005/I2, gateway-agnostic).

    Separates OUR cross-reference (``gateway_reference``, also the processor-side
    order id) from the processor's own id (``processor_transaction_id``); ``raw``
    is the polymorphic full processor payload. Never log
    ``processor_transaction_id`` / ``last_four`` / ``raw``.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(payment_status_enum, nullable=False)
    gateway: Mapped[str] = mapped_column(nullable=False)
    gateway_reference: Mapped[str] = mapped_column(nullable=False)
    # Optional client-supplied retry token (0025). When set, a retried pay with
    # the same key replays this row's outcome instead of charging again; the
    # partial unique index (invoice_id, idempotency_key) enforces one per key.
    idempotency_key: Mapped[str | None] = mapped_column(nullable=True)
    processor_transaction_id: Mapped[str | None] = mapped_column(nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(nullable=True)
    last_four: Mapped[str | None] = mapped_column(nullable=True)
    processor_response: Mapped[str | None] = mapped_column(nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
