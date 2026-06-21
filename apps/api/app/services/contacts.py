"""CRUD for per-client contact methods (phone / messenger / social).

Mirrors the per-fact CRUD pattern in ``app.services.facts`` — locate the
client under the calling advisor (D015 collapse), insert/patch/delete,
commit. No soft-delete: contacts are short, structured, and frequently
edited; revoking is a hard delete.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClientContact
from app.schemas.contacts import ClientContactCreate, ClientContactUpdate
from app.services.clients import _load_client_owned_by

logger = logging.getLogger("ov_black.contacts")


class ContactOutcome(str, enum.Enum):
    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    CONTACT_NOT_FOUND = "contact_not_found"


@dataclass(frozen=True, slots=True)
class ContactResult:
    outcome: ContactOutcome
    contact: ClientContact | None = None


async def list_client_contacts(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
) -> list[ClientContact]:
    """Return every contact row for a client, oldest-first."""
    rows = (
        (
            await session.execute(
                select(ClientContact)
                .where(ClientContact.client_id == client_id)
                .order_by(ClientContact.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def create_client_contact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    payload: ClientContactCreate,
) -> ContactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return ContactResult(ContactOutcome.CLIENT_NOT_FOUND)
    row = ClientContact(
        client_id=client.id,
        kind=payload.kind,
        value=payload.value,
        label=payload.label,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ContactResult(ContactOutcome.OK, contact=row)


async def update_client_contact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: ClientContactUpdate,
) -> ContactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return ContactResult(ContactOutcome.CLIENT_NOT_FOUND)
    row = (
        await session.execute(
            select(ClientContact).where(
                ClientContact.id == contact_id,
                ClientContact.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return ContactResult(ContactOutcome.CONTACT_NOT_FOUND)
    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return ContactResult(ContactOutcome.OK, contact=row)


async def delete_client_contact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> ContactOutcome:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return ContactOutcome.CLIENT_NOT_FOUND
    result = await session.execute(
        delete(ClientContact)
        .where(
            ClientContact.id == contact_id,
            ClientContact.client_id == client_id,
        )
        .returning(ClientContact.id)
    )
    if result.scalar_one_or_none() is None:
        return ContactOutcome.CONTACT_NOT_FOUND
    await session.commit()
    return ContactOutcome.OK
