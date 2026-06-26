"""Document vault CRUD + presigned-key helpers (M003/V3).

A document is a durable, household-scoped vault entry (0020). Like party members
it's authored by advisor or traveler (the actor is pinned server-side per
endpoint), client-scoped, and soft-archived so removing it never orphans history.

Authorization is enforced by the *router* (it resolves the caller's identity and
the client/itinerary it may touch) before calling in here; these functions take
an already-authorized ``client_id``. Access-resolution helpers are shared with
the party_members slice (``load_client_for_advisor`` / ``load_itinerary_client_id``
/ ``get_party_member``) so the same D015 404-collapse applies.

Discipline (R / D-VAULT): the ``s3_key`` is sensitive — never log it, never
return it. The router maps a document to a presigned URL on demand via
``VaultStorage``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClientDocument, DocumentActor, PartyMember
from app.schemas.client_documents import DocumentInitRequest, DocumentUpdate

logger = logging.getLogger("ov_black.client_documents")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def build_s3_key(*, client_id: uuid.UUID, document_id: uuid.UUID, file_name: str) -> str:
    """A deterministic, collision-free object key for a document.

    ``vault/{client_id}/{document_id}/{sanitized_name}`` — the document id makes
    it unique even if two uploads share a file name; the name is sanitized so a
    crafted upload name can't escape the prefix.
    """
    safe = _SAFE_NAME.sub("_", file_name).strip("._") or "document"
    return f"vault/{client_id}/{document_id}/{safe}"


# ── document CRUD (client_id already authorized by the caller) ────────────


async def list_documents(
    session: AsyncSession, *, client_id: uuid.UUID, include_archived: bool = False
) -> list[ClientDocument]:
    """The household's documents — newest first; active only by default."""
    stmt = select(ClientDocument).where(ClientDocument.client_id == client_id)
    if not include_archived:
        stmt = stmt.where(ClientDocument.archived_at.is_(None))
    stmt = stmt.order_by(ClientDocument.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_document(
    session: AsyncSession, *, client_id: uuid.UUID, document_id: uuid.UUID
) -> ClientDocument | None:
    """A document scoped to its client (so a leaked id can't cross households)."""
    return (
        await session.execute(
            select(ClientDocument).where(
                ClientDocument.id == document_id,
                ClientDocument.client_id == client_id,
            )
        )
    ).scalar_one_or_none()


async def _validate_party_member(
    session: AsyncSession, *, client_id: uuid.UUID, party_member_id: uuid.UUID
) -> bool:
    """True iff the member belongs to this client (else the link is rejected)."""
    member = (
        await session.execute(
            select(PartyMember.id).where(
                PartyMember.id == party_member_id,
                PartyMember.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    return member is not None


async def create_document(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    payload: DocumentInitRequest,
    actor: DocumentActor,
    recorded_by: uuid.UUID | None,
) -> ClientDocument:
    """Persist a pending document row (uploaded_at stays null until confirmed).

    The id is generated here so ``build_s3_key`` is deterministic. Raises
    ``ValueError('party_member_not_found')`` if a cross-client member is linked.
    """
    document_id = uuid.uuid4()
    if payload.party_member_id is not None:
        ok = await _validate_party_member(
            session, client_id=client_id, party_member_id=payload.party_member_id
        )
        if not ok:
            raise ValueError("party_member_not_found")

    s3_key = build_s3_key(client_id=client_id, document_id=document_id, file_name=payload.file_name)
    document = ClientDocument(
        id=document_id,
        client_id=client_id,
        party_member_id=payload.party_member_id,
        doc_type=payload.doc_type,
        label=payload.label,
        file_name=payload.file_name,
        content_type=payload.content_type,
        s3_key=s3_key,
        expires_at=payload.expires_at,
        notes=payload.notes,
        created_by_actor=actor,
        recorded_by=recorded_by,
    )
    session.add(document)
    await session.flush()
    await session.commit()
    await session.refresh(document)
    return document


async def mark_uploaded(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    size_bytes: int | None = None,
) -> ClientDocument | None:
    """Confirm the browser's S3 PUT succeeded; stamps ``uploaded_at``."""
    document = await get_document(session, client_id=client_id, document_id=document_id)
    if document is None:
        return None
    now = datetime.now(UTC)
    document.uploaded_at = now
    if size_bytes is not None:
        document.size_bytes = size_bytes
    document.updated_at = now
    await session.flush()
    await session.commit()
    await session.refresh(document)
    return document


async def update_document(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentUpdate,
) -> ClientDocument | None:
    """Patch document metadata (only set fields applied)."""
    document = await get_document(session, client_id=client_id, document_id=document_id)
    if document is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    if data.get("party_member_id") is not None:
        ok = await _validate_party_member(
            session, client_id=client_id, party_member_id=data["party_member_id"]
        )
        if not ok:
            raise ValueError("party_member_not_found")

    for field, value in data.items():
        setattr(document, field, value)
    document.updated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    await session.refresh(document)
    return document


async def archive_document(
    session: AsyncSession, *, client_id: uuid.UUID, document_id: uuid.UUID
) -> ClientDocument | None:
    """Soft-delete: hide from the active list, keep the row + S3 object.

    S3 object cleanup is deferred to a bucket lifecycle policy (V3 resume hook).
    """
    document = await get_document(session, client_id=client_id, document_id=document_id)
    if document is None:
        return None
    if document.archived_at is None:
        now = datetime.now(UTC)
        document.archived_at = now
        document.updated_at = now
        await session.flush()
        await session.commit()
        await session.refresh(document)
    return document


async def member_names_for(session: AsyncSession, *, client_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """A {member_id: full_name} map for resolving ``party_member_name`` on read."""
    rows = (
        await session.execute(
            select(PartyMember.id, PartyMember.full_name).where(PartyMember.client_id == client_id)
        )
    ).all()
    return {row[0]: row[1] for row in rows}
