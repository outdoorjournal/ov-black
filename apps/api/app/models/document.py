"""ClientDocument model — secure document vault (0020 — M003/V3).

A durable, client-scoped (household) document: passport, visa, insurance, etc.
The bytes live in S3 under SSE-KMS; only metadata + the opaque ``s3_key`` live
here. The key is NEVER returned to a client or logged — reads mint a presigned
URL on demand.

A document may be optionally attributed to a specific ``party_member`` (e.g. a
child's passport) without changing household ownership.

Schema is owned by ``supabase/migrations/0020_client_documents.sql`` — this class
is a read/write surface only.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class DocumentType(str, enum.Enum):
    """Mirrors the public.document_type enum from 0020."""

    passport = "passport"
    visa = "visa"
    drivers_license = "drivers_license"
    national_id = "national_id"
    vaccination = "vaccination"
    insurance = "insurance"
    loyalty_card = "loyalty_card"
    other = "other"


class DocumentActor(str, enum.Enum):
    """Mirrors the public.document_actor enum from 0020.

    Who uploaded / last touched a document. Unlike party members, the agent does
    not handle files — only the advisor and the traveler (self-service).
    """

    advisor = "advisor"
    traveler = "traveler"


# Postgres owns the types (D003/D020); SQLAlchemy binds with create_type=False.
document_type_enum = PGEnum(
    DocumentType,
    name="document_type",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)

document_actor_enum = PGEnum(
    DocumentActor,
    name="document_actor",
    schema="public",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class ClientDocument(Base):
    """A durable, client-scoped vault entry (0020 — M003/V3)."""

    __tablename__ = "client_documents"

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
    # Optional attribution to a household member; on delete the link clears.
    party_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("party_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    doc_type: Mapped[DocumentType] = mapped_column(document_type_enum, nullable=False)
    label: Mapped[str | None] = mapped_column(nullable=True)
    file_name: Mapped[str] = mapped_column(nullable=False)
    content_type: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The opaque S3 object key — NEVER returned to a client or logged.
    s3_key: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_actor: Mapped[DocumentActor] = mapped_column(document_actor_enum, nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
