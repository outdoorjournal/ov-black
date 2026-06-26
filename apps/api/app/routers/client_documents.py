"""Secure document vault surfaces (M003/V3).

Like the party-member roster, the vault is a household asset maintained by two
actors, so this router exposes parallel surfaces that all funnel into
``services.client_documents``:

- **Advisor** (``/clients/{id}/documents``, ``require_advisor``) — scoped to
  clients the advisor owns; writes stamp ``actor=advisor``.
- **Traveler** (``/me/documents``, ``require_user``) — the caller's own
  household, resolved from their Supabase identity; writes stamp ``actor=traveler``.
- **Per-trip read-only** (``/itineraries/{id}/documents``) — list the itinerary's
  client's documents (advisor OR linked traveler). Documents are client-scoped,
  so they're inherently available on every trip; there is no per-trip attach.

Upload is a two-step presigned flow: ``POST …/documents`` persists metadata and
returns a presigned PUT (browser uploads straight to S3), then
``POST …/{id}/complete`` confirms. Downloads mint a presigned GET on demand. The
S3 key is never returned or logged (R / D-VAULT). All surfaces 404 the D015 way
on a client/itinerary the caller can't touch — no 403 that would confirm
existence.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, DocumentActor
from app.schemas.client_documents import (
    DocumentCompleteRequest,
    DocumentDetail,
    DocumentDownloadResponse,
    DocumentInitRequest,
    DocumentInitResponse,
    DocumentListResponse,
    DocumentUpdate,
)
from app.services.client_documents import (
    archive_document,
    create_document,
    get_document,
    list_documents,
    mark_uploaded,
    member_names_for,
    update_document,
)
from app.services.clients import resolve_client_for_auth_user
from app.services.party_members import (
    load_client_for_advisor,
    load_itinerary_client_id,
)
from app.vault.storage import VaultStorage, get_vault_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import ClientDocument

logger = logging.getLogger("ov_black.routers.client_documents")

router = APIRouter(tags=["documents"])

_NOT_FOUND = HTTPException(status_code=404, detail="client_not_found")
_ITIN_NOT_FOUND = HTTPException(status_code=404, detail="itinerary_not_found")
_DOC_NOT_FOUND = HTTPException(status_code=404, detail="document_not_found")
_MEMBER_NOT_FOUND = HTTPException(status_code=404, detail="party_member_not_found")


def _uid(user: AuthenticatedUser) -> uuid.UUID:
    try:
        return uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        raise _NOT_FOUND from None


def _today() -> date:
    return datetime.now(UTC).date()


def _detail(doc: ClientDocument, *, member_names: dict[uuid.UUID, str]) -> DocumentDetail:
    name = member_names.get(doc.party_member_id) if doc.party_member_id is not None else None
    return DocumentDetail.from_model(doc, today=_today(), party_member_name=name)


# ── shared resolution ────────────────────────────────────────────────────


async def _resolve_traveler_client(session: AsyncSession, user: AuthenticatedUser) -> Client:
    client = await resolve_client_for_auth_user(session, user_id=_uid(user), email=user.email)
    if client is None:
        raise _NOT_FOUND
    return client


async def _authorize_itinerary_client(
    session: AsyncSession, user: AuthenticatedUser, itinerary_id: uuid.UUID
) -> uuid.UUID:
    """The itinerary's client_id iff the caller (advisor OR traveler) may touch it."""
    client_id = await load_itinerary_client_id(session, itinerary_id=itinerary_id)
    if client_id is None:
        raise _ITIN_NOT_FOUND
    client = await session.get(Client, client_id)
    if client is None:  # pragma: no cover — FK guarantees presence
        raise _ITIN_NOT_FOUND
    uid = _uid(user)
    if client.owner_id == uid:
        return client_id
    own = await resolve_client_for_auth_user(session, user_id=uid, email=user.email)
    if own is not None and own.id == client_id:
        return client_id
    raise _ITIN_NOT_FOUND


async def _list_for_client(
    session: AsyncSession, *, client_id: uuid.UUID, include_archived: bool = False
) -> DocumentListResponse:
    docs = await list_documents(session, client_id=client_id, include_archived=include_archived)
    names = await member_names_for(session, client_id=client_id)
    return DocumentListResponse(documents=[_detail(d, member_names=names) for d in docs])


async def _init(
    session: AsyncSession,
    storage: VaultStorage,
    *,
    client_id: uuid.UUID,
    payload: DocumentInitRequest,
    actor: DocumentActor,
    recorded_by: uuid.UUID,
) -> DocumentInitResponse:
    try:
        doc = await create_document(
            session,
            client_id=client_id,
            payload=payload,
            actor=actor,
            recorded_by=recorded_by,
        )
    except ValueError as exc:
        if str(exc) == "party_member_not_found":
            raise _MEMBER_NOT_FOUND from None
        raise
    names = await member_names_for(session, client_id=client_id)
    upload_url = storage.upload_url(key=doc.s3_key, content_type=doc.content_type)
    return DocumentInitResponse(document=_detail(doc, member_names=names), upload_url=upload_url)


async def _complete(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentCompleteRequest,
) -> DocumentDetail:
    doc = await mark_uploaded(
        session,
        client_id=client_id,
        document_id=document_id,
        size_bytes=payload.size_bytes,
    )
    if doc is None:
        raise _DOC_NOT_FOUND
    names = await member_names_for(session, client_id=client_id)
    return _detail(doc, member_names=names)


async def _download(
    session: AsyncSession,
    storage: VaultStorage,
    *,
    client_id: uuid.UUID,
    document_id: uuid.UUID,
) -> DocumentDownloadResponse:
    doc = await get_document(session, client_id=client_id, document_id=document_id)
    if doc is None:
        raise _DOC_NOT_FOUND
    url = storage.download_url(key=doc.s3_key, file_name=doc.file_name)
    return DocumentDownloadResponse(url=url)


async def _update(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentUpdate,
) -> DocumentDetail:
    try:
        doc = await update_document(
            session, client_id=client_id, document_id=document_id, payload=payload
        )
    except ValueError as exc:
        if str(exc) == "party_member_not_found":
            raise _MEMBER_NOT_FOUND from None
        raise
    if doc is None:
        raise _DOC_NOT_FOUND
    names = await member_names_for(session, client_id=client_id)
    return _detail(doc, member_names=names)


async def _archive(
    session: AsyncSession, *, client_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentDetail:
    doc = await archive_document(session, client_id=client_id, document_id=document_id)
    if doc is None:
        raise _DOC_NOT_FOUND
    names = await member_names_for(session, client_id=client_id)
    return _detail(doc, member_names=names)


# ── advisor surface ──────────────────────────────────────────────────────


async def _advisor_client_id(
    session: AsyncSession, user: AuthenticatedUser, client_id: uuid.UUID
) -> uuid.UUID:
    if await load_client_for_advisor(session, advisor_id=_uid(user), client_id=client_id) is None:
        raise _NOT_FOUND
    return client_id


@router.get(
    "/clients/{client_id}/documents",
    response_model=DocumentListResponse,
    summary="List a client's vault documents (advisor).",
)
async def list_client_documents_endpoint(
    client_id: uuid.UUID,
    include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    await _advisor_client_id(session, user, client_id)
    return await _list_for_client(session, client_id=client_id, include_archived=include_archived)


@router.post(
    "/clients/{client_id}/documents",
    response_model=DocumentInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Begin a document upload for a client (advisor).",
)
async def init_client_document_endpoint(
    client_id: uuid.UUID,
    payload: DocumentInitRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    storage: VaultStorage = Depends(get_vault_storage),
) -> DocumentInitResponse:
    await _advisor_client_id(session, user, client_id)
    return await _init(
        session,
        storage,
        client_id=client_id,
        payload=payload,
        actor=DocumentActor.advisor,
        recorded_by=_uid(user),
    )


@router.post(
    "/clients/{client_id}/documents/{document_id}/complete",
    response_model=DocumentDetail,
    summary="Confirm a client document upload (advisor).",
)
async def complete_client_document_endpoint(
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentCompleteRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    await _advisor_client_id(session, user, client_id)
    return await _complete(session, client_id=client_id, document_id=document_id, payload=payload)


@router.get(
    "/clients/{client_id}/documents/{document_id}/download",
    response_model=DocumentDownloadResponse,
    summary="Get a presigned download URL for a client document (advisor).",
)
async def download_client_document_endpoint(
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    storage: VaultStorage = Depends(get_vault_storage),
) -> DocumentDownloadResponse:
    await _advisor_client_id(session, user, client_id)
    return await _download(session, storage, client_id=client_id, document_id=document_id)


@router.patch(
    "/clients/{client_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Edit a client document's metadata (advisor).",
)
async def update_client_document_endpoint(
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    await _advisor_client_id(session, user, client_id)
    return await _update(session, client_id=client_id, document_id=document_id, payload=payload)


@router.delete(
    "/clients/{client_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Archive a client document (advisor).",
)
async def archive_client_document_endpoint(
    client_id: uuid.UUID,
    document_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    await _advisor_client_id(session, user, client_id)
    return await _archive(session, client_id=client_id, document_id=document_id)


# ── traveler self-service surface ────────────────────────────────────────


@router.get(
    "/me/documents",
    response_model=DocumentListResponse,
    summary="List my own household's vault documents (traveler).",
)
async def list_my_documents_endpoint(
    include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    client = await _resolve_traveler_client(session, user)
    return await _list_for_client(session, client_id=client.id, include_archived=include_archived)


@router.post(
    "/me/documents",
    response_model=DocumentInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Begin a document upload for my own household (traveler).",
)
async def init_my_document_endpoint(
    payload: DocumentInitRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    storage: VaultStorage = Depends(get_vault_storage),
) -> DocumentInitResponse:
    client = await _resolve_traveler_client(session, user)
    return await _init(
        session,
        storage,
        client_id=client.id,
        payload=payload,
        actor=DocumentActor.traveler,
        recorded_by=_uid(user),
    )


@router.post(
    "/me/documents/{document_id}/complete",
    response_model=DocumentDetail,
    summary="Confirm one of my document uploads (traveler).",
)
async def complete_my_document_endpoint(
    document_id: uuid.UUID,
    payload: DocumentCompleteRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    client = await _resolve_traveler_client(session, user)
    return await _complete(session, client_id=client.id, document_id=document_id, payload=payload)


@router.get(
    "/me/documents/{document_id}/download",
    response_model=DocumentDownloadResponse,
    summary="Get a presigned download URL for one of my documents (traveler).",
)
async def download_my_document_endpoint(
    document_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    storage: VaultStorage = Depends(get_vault_storage),
) -> DocumentDownloadResponse:
    client = await _resolve_traveler_client(session, user)
    return await _download(session, storage, client_id=client.id, document_id=document_id)


@router.patch(
    "/me/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Edit one of my document's metadata (traveler).",
)
async def update_my_document_endpoint(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    client = await _resolve_traveler_client(session, user)
    return await _update(session, client_id=client.id, document_id=document_id, payload=payload)


@router.delete(
    "/me/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Archive one of my documents (traveler).",
)
async def archive_my_document_endpoint(
    document_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentDetail:
    client = await _resolve_traveler_client(session, user)
    return await _archive(session, client_id=client.id, document_id=document_id)


# ── per-trip read-only (who has what on this itinerary's household) ───────


@router.get(
    "/itineraries/{itinerary_id}/documents",
    response_model=DocumentListResponse,
    summary="List the itinerary's client's vault documents (advisor or traveler).",
)
async def list_itinerary_documents_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentListResponse:
    client_id = await _authorize_itinerary_client(session, user, itinerary_id)
    return await _list_for_client(session, client_id=client_id)
