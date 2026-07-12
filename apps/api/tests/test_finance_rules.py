"""Deposit / final quick-action seeding (doc/thoughts.md §5, finance_rules).

Integration tests against the local Supabase Postgres (skipped without it, like
test_invoices): the deposit schedule (flights 100% / else 20%), a single
multi-currency draft, the final balance, and re-running a deposit not double-billing.
"""

from __future__ import annotations

import socket
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import CostKind, Invoice, NodeStatus, NodeType
from app.services.finance_rules import (
    deposit_due,
    seed_deposit_invoice,
    seed_final_invoice,
)
from app.services.invoices import InvoiceView, get_invoice
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    add_node,
    create_itinerary,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 54322))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="fin-advisor")


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(*itinerary_ids: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
    finally:
        await engine.dispose()


async def _node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    node_type: NodeType,
    amount: str,
    currency: str,
    title: str,
) -> uuid.UUID:
    node = await add_node(
        session,
        _actor(),
        itinerary_id=itinerary_id,
        type=node_type,
        status=NodeStatus.approved,
        title=title,
        cost_amount=Decimal(amount),
        cost_currency=currency,
        cost_kind=CostKind.total,
    )
    assert not isinstance(node, ItineraryError)
    return node.id


def test_deposit_due_schedule() -> None:
    # Pure rule: flights 100%, everything else 20%.
    assert deposit_due(Decimal("1000.00"), NodeType.flight) == Decimal("1000.00")
    assert deposit_due(Decimal("1000.00"), NodeType.hotel) == Decimal("200.00")
    assert deposit_due(Decimal("2500.00"), NodeType.experience) == Decimal("500.00")


@integration
@pytest.mark.asyncio
async def test_deposit_splits_flights_full_and_others_twenty(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="dep")
    try:
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.flight,
            amount="1000.00",
            currency="USD",
            title="BA flight",
        )
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.hotel,
            amount="2000.00",
            currency="USD",
            title="Aman",
        )
        invoice = await seed_deposit_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(invoice, Invoice)
        assert invoice.label == "Deposit"
        view = await get_invoice(db_session, invoice.id)
        assert isinstance(view, InvoiceView)
        # flight 100% (1000) + hotel 20% (400) = 1400 USD.
        assert view.subtotals == {"USD": Decimal("1400.00")}
        assert len(view.lines) == 2
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_deposit_holds_multiple_currencies_in_one_invoice(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="multi")
    try:
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.flight,
            amount="1000.00",
            currency="EUR",
            title="LH flight",
        )
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.hotel,
            amount="2000.00",
            currency="GBP",
            title="Claridge's",
        )
        invoice = await seed_deposit_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(invoice, Invoice)
        view = await get_invoice(db_session, invoice.id)
        assert isinstance(view, InvoiceView)
        # One invoice, two native currencies: EUR flight 100%, GBP hotel 20%.
        assert view.subtotals == {"EUR": Decimal("1000.00"), "GBP": Decimal("400.00")}
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_final_bills_remaining_after_deposit(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="final")
    try:
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.flight,
            amount="1000.00",
            currency="USD",
            title="Flight",
        )
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.hotel,
            amount="2000.00",
            currency="USD",
            title="Hotel",
        )
        dep = await seed_deposit_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(dep, Invoice)

        final = await seed_final_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(final, Invoice)
        assert final.label == "Balance"
        view = await get_invoice(db_session, final.id)
        assert isinstance(view, InvoiceView)
        # Flight fully deposited (100%) → nothing left; hotel remaining 1600.
        assert view.subtotals == {"USD": Decimal("1600.00")}
        assert len(view.lines) == 1
    finally:
        await _cleanup(itin.id)


@integration
@pytest.mark.asyncio
async def test_second_deposit_finds_nothing_to_do(db_session: AsyncSession) -> None:
    itin = await create_itinerary(db_session, _actor(), title="twice")
    try:
        await _node(
            db_session,
            itin.id,
            node_type=NodeType.hotel,
            amount="2000.00",
            currency="USD",
            title="Hotel",
        )
        first = await seed_deposit_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(first, Invoice)
        # The deposit level is already met — a second run has nothing to charge.
        again = await seed_deposit_invoice(db_session, _actor(), itinerary_id=itin.id)
        assert isinstance(again, ItineraryError)
        assert again.detail == "nothing_to_deposit"
    finally:
        await _cleanup(itin.id)
