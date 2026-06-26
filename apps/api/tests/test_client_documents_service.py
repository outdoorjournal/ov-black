"""Document vault service (M003/V3) — durable, client-scoped storage.

Integration tests (gated on local Supabase). They exercise the vault behaviours:
client-scoped CRUD, the two-step upload (init → mark_uploaded), soft-archive,
the optional party-member link (incl. cross-client rejection), notes round-trip,
and the redaction guarantee that the s3_key never leaks into a log record.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import Client, DocumentActor, PartyMember, PartyMemberActor
from app.schemas.client_documents import DocumentInitRequest, DocumentUpdate
from app.services.client_documents import (
    archive_document,
    create_document,
    get_document,
    list_documents,
    mark_uploaded,
    member_names_for,
    update_document,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, integration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = integration


@pytest_asyncio.fixture()
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


class _Household:
    def __init__(self, advisor_id: uuid.UUID, client_id: uuid.UUID) -> None:
        self.advisor_id = advisor_id
        self.client_id = client_id


async def _insert_auth_user(s: AsyncSession, uid: uuid.UUID, email: str) -> None:
    await s.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": uid, "email": email},
    )


async def _make_client(s: AsyncSession) -> _Household:
    advisor_id = uuid.uuid4()
    await _insert_auth_user(s, advisor_id, f"adv-{advisor_id.hex[:8]}@example.com")
    client = Client(
        owner_id=advisor_id,
        full_name="Vault Household",
        email=f"head-{advisor_id.hex[:8]}@example.com",
    )
    s.add(client)
    await s.commit()
    await s.refresh(client)
    return _Household(advisor_id, client.id)


@pytest_asyncio.fixture()
async def household(session: AsyncSession) -> AsyncIterator[_Household]:
    h = await _make_client(session)
    try:
        yield h
    finally:
        await session.execute(
            text("delete from public.clients where id = :cid"), {"cid": h.client_id}
        )
        await session.execute(text("delete from auth.users where id = :id"), {"id": h.advisor_id})
        await session.commit()


def _init(**kw: object) -> DocumentInitRequest:
    base: dict[str, object] = {
        "doc_type": "passport",
        "file_name": "passport.pdf",
        "content_type": "application/pdf",
    }
    base.update(kw)
    return DocumentInitRequest(**base)  # type: ignore[arg-type]


async def test_create_persists_pending_then_mark_uploaded(
    session: AsyncSession, household: _Household
) -> None:
    doc = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="My passport", notes="renew before Japan"),
        actor=DocumentActor.traveler,
        recorded_by=household.advisor_id,
    )
    assert doc.uploaded_at is None  # pending until confirmed
    assert doc.s3_key.startswith(f"vault/{household.client_id}/{doc.id}/")
    assert doc.created_by_actor is DocumentActor.traveler
    assert doc.notes == "renew before Japan"

    confirmed = await mark_uploaded(
        session, client_id=household.client_id, document_id=doc.id, size_bytes=2048
    )
    assert confirmed is not None
    assert confirmed.uploaded_at is not None
    assert confirmed.size_bytes == 2048


async def test_list_is_newest_first_and_active_only(
    session: AsyncSession, household: _Household
) -> None:
    a = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="A"),
        actor=DocumentActor.advisor,
        recorded_by=household.advisor_id,
    )
    b = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="B"),
        actor=DocumentActor.advisor,
        recorded_by=household.advisor_id,
    )
    await archive_document(session, client_id=household.client_id, document_id=a.id)

    active = await list_documents(session, client_id=household.client_id)
    assert [d.id for d in active] == [b.id]  # a is archived/hidden, b newest
    with_archived = await list_documents(
        session, client_id=household.client_id, include_archived=True
    )
    assert {d.id for d in with_archived} == {a.id, b.id}


async def test_update_applies_only_set_fields(session: AsyncSession, household: _Household) -> None:
    doc = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="Before", notes="n1"),
        actor=DocumentActor.advisor,
        recorded_by=household.advisor_id,
    )
    updated = await update_document(
        session,
        client_id=household.client_id,
        document_id=doc.id,
        payload=DocumentUpdate(label="After"),
    )
    assert updated is not None
    assert updated.label == "After"
    assert updated.notes == "n1"  # untouched


async def test_get_is_client_scoped(session: AsyncSession, household: _Household) -> None:
    doc = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(),
        actor=DocumentActor.advisor,
        recorded_by=household.advisor_id,
    )
    other = await _make_client(session)
    try:
        # The same id under a different client must not resolve.
        leaked = await get_document(session, client_id=other.client_id, document_id=doc.id)
        assert leaked is None
    finally:
        await session.execute(
            text("delete from public.clients where id = :cid"),
            {"cid": other.client_id},
        )
        await session.execute(
            text("delete from auth.users where id = :id"), {"id": other.advisor_id}
        )
        await session.commit()


async def test_party_member_link_validates_same_client(
    session: AsyncSession, household: _Household
) -> None:
    member = PartyMember(
        client_id=household.client_id,
        full_name="Kiddo",
        created_by_actor=PartyMemberActor.traveler,
        updated_by_actor=PartyMemberActor.traveler,
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    # Linking a member of this household is fine, and resolves a name on read.
    doc = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="Kid passport", party_member_id=member.id),
        actor=DocumentActor.traveler,
        recorded_by=household.advisor_id,
    )
    assert doc.party_member_id == member.id
    names = await member_names_for(session, client_id=household.client_id)
    assert names[member.id] == "Kiddo"

    # A member from another household is rejected (no cross-household linking).
    other = await _make_client(session)
    foreign = PartyMember(
        client_id=other.client_id,
        full_name="Stranger",
        created_by_actor=PartyMemberActor.advisor,
        updated_by_actor=PartyMemberActor.advisor,
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)
    try:
        with pytest.raises(ValueError, match="party_member_not_found"):
            await create_document(
                session,
                client_id=household.client_id,
                payload=_init(party_member_id=foreign.id),
                actor=DocumentActor.traveler,
                recorded_by=household.advisor_id,
            )
    finally:
        await session.execute(
            text("delete from public.clients where id = :cid"),
            {"cid": other.client_id},
        )
        await session.execute(
            text("delete from auth.users where id = :id"), {"id": other.advisor_id}
        )
        await session.commit()


async def test_s3_key_never_leaks_into_logs(
    session: AsyncSession,
    household: _Household,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Redaction sweep (R / D-VAULT): the opaque key stays out of every record."""
    caplog.set_level(logging.DEBUG)
    doc = await create_document(
        session,
        client_id=household.client_id,
        payload=_init(label="secret"),
        actor=DocumentActor.traveler,
        recorded_by=household.advisor_id,
    )
    await mark_uploaded(session, client_id=household.client_id, document_id=doc.id, size_bytes=1)
    await update_document(
        session,
        client_id=household.client_id,
        document_id=doc.id,
        payload=DocumentUpdate(notes="touch"),
    )
    await archive_document(session, client_id=household.client_id, document_id=doc.id)

    for rec in caplog.records:
        blob = rec.getMessage() + " " + str(rec.args) + " " + str(rec.__dict__)
        assert doc.s3_key not in blob, f"s3_key leaked into log: {rec.name}"
