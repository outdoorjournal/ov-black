"""``/me`` self-service surface — the cross-trip invoice listing (D4).

Integration (gated on local Supabase). Exercises
:func:`app.services.invoices.list_invoices_for_client` — every invoice across a
client's itineraries, paired with its itinerary, with another client's invoices
never leaking in — plus the ``GET /me/invoices`` JWT guard.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import InvoiceLineKind
from app.services.invoices import add_line_item, create_invoice, list_invoices_for_client
from app.services.itineraries import ActorContext, ActorKind
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = integration


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="me-test")


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _insert_client(session: AsyncSession, owner_id: uuid.UUID, name: str) -> uuid.UUID:
    cid = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into public.clients (id, owner_id, full_name, email)
            values (:id, :owner, :name, :email)
            """
        ),
        {"id": cid, "owner": owner_id, "name": name, "email": f"{name}@x.com"},
    )
    await session.commit()
    return cid


async def _charge(session: AsyncSession, itinerary_id: uuid.UUID, label: str, amount: str) -> None:
    invoice = await create_invoice(
        session, _actor(), itinerary_id=itinerary_id, label=label, currency="USD"
    )
    assert not isinstance(invoice, Exception)
    await add_line_item(
        session,
        _actor(),
        invoice_id=invoice.id,  # type: ignore[union-attr]
        description="Deposit",
        amount=Decimal(amount),
        currency="USD",
        kind=InvoiceLineKind.charge,
    )


async def _cleanup(
    *itinerary_ids: uuid.UUID,
    client_ids: tuple[uuid.UUID, ...],
    owner: uuid.UUID,
) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
            for cid in client_ids:
                await conn.execute(text("delete from public.clients where id = :i"), {"i": cid})
            await conn.execute(text("delete from auth.users where id = :i"), {"i": owner})
    finally:
        await engine.dispose()


@integration
@pytest.mark.asyncio
async def test_list_invoices_for_client_spans_trips_and_isolates(
    db_session: AsyncSession,
) -> None:
    owner = uuid.uuid4()
    await db_session.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": owner, "email": f"{owner}@x.com"},
    )
    await db_session.commit()

    client_a = await _insert_client(db_session, owner, "alpha")
    client_b = await _insert_client(db_session, owner, "bravo")
    trip1 = await insert_itinerary(db_session, title="Kyoto", client_id=client_a)
    trip2 = await insert_itinerary(db_session, title="Patagonia", client_id=client_a)
    trip_b = await insert_itinerary(db_session, title="Bravo trip", client_id=client_b)
    try:
        await _charge(db_session, trip1, "Deposit", "1000.00")
        await _charge(db_session, trip2, "Balance", "2500.00")
        await _charge(db_session, trip_b, "Other", "999.00")

        rows = await list_invoices_for_client(db_session, client_a)
        assert len(rows) == 2  # client B's invoice is excluded
        by_label = {view.invoice.label: (view, itin) for view, itin in rows}
        assert by_label["Deposit"][0].total == Decimal("1000.00")
        assert by_label["Deposit"][1].title == "Kyoto"
        assert by_label["Balance"][0].total == Decimal("2500.00")
        assert by_label["Balance"][1].title == "Patagonia"

        # No client at all → empty.
        assert await list_invoices_for_client(db_session, uuid.uuid4()) == []
    finally:
        await _cleanup(trip1, trip2, trip_b, client_ids=(client_a, client_b), owner=owner)


def test_my_invoices_requires_jwt(client: Any) -> None:
    resp = client.get("/me/invoices")
    assert resp.status_code == 401
