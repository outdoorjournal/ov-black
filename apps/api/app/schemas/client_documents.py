"""Pydantic shapes for the secure document vault (M003/V3).

A document is a durable, household-scoped vault entry (0020), reused across every
itinerary. Upload is a two-step presigned flow: ``init`` persists the metadata +
mints a presigned PUT (the browser uploads straight to S3), then ``complete``
confirms. Reads mint a presigned GET on demand.

Discipline (R / D-VAULT): the response shapes carry metadata only — never the
``s3_key`` and never a stored URL. The presigned upload URL is returned exactly
once (from ``init``) to the authorized uploader; download URLs are minted
per-request from the dedicated endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import ClientDocument, DocumentActor, DocumentType

# Passport-renewal rule: warn when a document expires within ~6 months.
_EXPIRES_SOON_DAYS = 183


# ── write shapes (actor fixed server-side) ───────────────────────────────


class DocumentInitRequest(BaseModel):
    """Begin an upload: persist metadata + mint a presigned PUT."""

    model_config = ConfigDict(extra="forbid")

    doc_type: DocumentType
    file_name: str = Field(min_length=1, max_length=400)
    content_type: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    party_member_id: uuid.UUID | None = None
    expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class DocumentUpdate(BaseModel):
    """All-optional patch; only fields explicitly set are applied."""

    model_config = ConfigDict(extra="forbid")

    doc_type: DocumentType | None = None
    label: str | None = Field(default=None, max_length=200)
    party_member_id: uuid.UUID | None = None
    expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


# ── read shapes ──────────────────────────────────────────────────────────


class DocumentDetail(BaseModel):
    """Metadata view — never carries the s3_key or a URL."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    client_id: uuid.UUID
    party_member_id: uuid.UUID | None
    party_member_name: str | None
    doc_type: DocumentType
    label: str | None
    file_name: str
    content_type: str
    size_bytes: int | None
    expires_at: date | None
    notes: str | None
    expired: bool
    expires_soon: bool
    uploaded_at: datetime | None
    created_by_actor: DocumentActor
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(
        cls,
        doc: ClientDocument,
        *,
        today: date,
        party_member_name: str | None = None,
    ) -> DocumentDetail:
        expired = doc.expires_at is not None and doc.expires_at < today
        expires_soon = (
            doc.expires_at is not None
            and not expired
            and doc.expires_at <= today + timedelta(days=_EXPIRES_SOON_DAYS)
        )
        return cls(
            id=doc.id,
            client_id=doc.client_id,
            party_member_id=doc.party_member_id,
            party_member_name=party_member_name,
            doc_type=doc.doc_type,
            label=doc.label,
            file_name=doc.file_name,
            content_type=doc.content_type,
            size_bytes=doc.size_bytes,
            expires_at=doc.expires_at,
            notes=doc.notes,
            expired=expired,
            expires_soon=expires_soon,
            uploaded_at=doc.uploaded_at,
            created_by_actor=doc.created_by_actor,
            archived_at=doc.archived_at,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


class DocumentInitResponse(BaseModel):
    """The created (pending) document + the one-time presigned PUT URL."""

    model_config = ConfigDict(extra="forbid")

    document: DocumentDetail
    upload_url: str


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentDetail]


class DocumentCompleteRequest(BaseModel):
    """Confirm the S3 PUT succeeded; optionally record the byte size."""

    model_config = ConfigDict(extra="forbid")

    size_bytes: int | None = Field(default=None, ge=0)


class DocumentDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
