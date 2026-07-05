"""``/me`` self-service surface — the cross-trip invoice listing (D4).

Integration (gated on local Supabase). Exercises
:func:`app.services.invoices.list_invoices_for_client` — every invoice across a
client's itineraries, paired with its itinerary, with another client's invoices
never leaking in — plus the ``GET /me/invoices`` JWT guard.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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


async def _insert_linked_client(
    session: AsyncSession, owner_id: uuid.UUID, auth_user_id: uuid.UUID, name: str
) -> uuid.UUID:
    cid = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into public.clients (id, owner_id, auth_user_id, full_name, email)
            values (:id, :owner, :auth, :name, :email)
            """
        ),
        {
            "id": cid,
            "owner": owner_id,
            "auth": auth_user_id,
            "name": name,
            "email": f"{name}@x.com",
        },
    )
    await session.commit()
    return cid


async def _insert_profile_fact(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    recorded_by: uuid.UUID,
    redacted: bool = False,
) -> None:
    await session.execute(
        text(
            """
            insert into public.profile_facts
                (id, client_id, kind, text, source_kind, recorded_by, redacted_at)
            values (:id, :client, cast('preference' as public.profile_fact_kind),
                    :text, cast('traveler_told' as public.fact_source_kind),
                    :rec, :redacted_at)
            """
        ),
        {
            "id": uuid.uuid4(),
            "client": client_id,
            "text": "loves onsen towns",
            "rec": recorded_by,
            "redacted_at": datetime(2026, 6, 30, tzinfo=UTC) if redacted else None,
        },
    )
    await session.commit()


async def _insert_session(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    audience: str,
    started_at: datetime,
    itinerary_id: uuid.UUID | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into public.agent_sessions
                (id, client_id, itinerary_id, agentcore_session_id, audience, started_at)
            values (:id, :client, :itin, :acs, cast(:aud as session_audience), :started)
            """
        ),
        {
            "id": sid,
            "client": client_id,
            "itin": itinerary_id,
            "acs": str(sid),
            "aud": audience,
            "started": started_at,
        },
    )
    await session.commit()
    return sid


@integration
@pytest.mark.asyncio
async def test_list_my_itineraries_excludes_forks(db_session: AsyncSession) -> None:
    """Basecamp lists official baselines only — a fork is the traveler's private
    'My version', reached via the two-version toggle, never a standalone trip."""
    from app.auth import AuthenticatedUser
    from app.routers.me import list_my_itineraries_endpoint

    owner = uuid.uuid4()
    traveler = uuid.uuid4()
    for uid in (owner, traveler):
        await db_session.execute(
            text(
                """
                insert into auth.users (id, email, aud, role, instance_id)
                values (:id, :email, 'authenticated', 'authenticated',
                        '00000000-0000-0000-0000-000000000000')
                """
            ),
            {"id": uid, "email": f"{uid}@x.com"},
        )
    await db_session.commit()

    client_id = await _insert_linked_client(db_session, owner, traveler, "fork-list-traveler")
    baseline = await insert_itinerary(db_session, title="Official Kyoto", client_id=client_id)
    fork = await insert_itinerary(db_session, title="Official Kyoto (fork)", client_id=client_id)
    try:
        await db_session.execute(
            text(
                "update public.itineraries set forked_from_id = :b, "
                "fork_status = cast('open' as public.fork_status) where id = :f"
            ),
            {"b": baseline, "f": fork},
        )
        await db_session.commit()

        user = AuthenticatedUser(
            sub=str(traveler), email=f"{traveler}@x.com", role="authenticated", claims={}
        )
        resp = await list_my_itineraries_endpoint(user=user, session=db_session)
        ids = {it.id for it in resp.itineraries}
        assert baseline in ids
        assert fork not in ids
    finally:
        await _cleanup(baseline, fork, client_ids=(client_id,), owner=owner)
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": traveler})
        finally:
            await engine.dispose()


@integration
@pytest.mark.asyncio
async def test_onboarding_session_ignores_advisor_audience(
    db_session: AsyncSession,
) -> None:
    """Basecamp must resolve the traveler's session, never a newer advisor one.

    Regression: an advisor session opened about the client (Command Center)
    used to shadow the traveler's session here because the query picked the
    most-recent open session across all audiences. The traveler's chat then
    POSTed turns to an advisor session and the existence-hiding authz 404'd.
    """
    from app.auth import AuthenticatedUser
    from app.routers.me import get_my_onboarding_session_endpoint

    owner = uuid.uuid4()
    traveler = uuid.uuid4()
    for uid in (owner, traveler):
        await db_session.execute(
            text(
                """
                insert into auth.users (id, email, aud, role, instance_id)
                values (:id, :email, 'authenticated', 'authenticated',
                        '00000000-0000-0000-0000-000000000000')
                """
            ),
            {"id": uid, "email": f"{uid}@x.com"},
        )
    await db_session.commit()

    client_id = await _insert_linked_client(db_session, owner, traveler, "kyoto-traveler")
    try:
        traveler_sid = await _insert_session(
            db_session,
            client_id=client_id,
            audience="traveler",
            started_at=datetime(2026, 6, 29, 2, 0, 0, tzinfo=UTC),
        )
        # Advisor session is newer — it would win a naive most-recent query.
        await _insert_session(
            db_session,
            client_id=client_id,
            audience="advisor",
            started_at=datetime(2026, 6, 29, 5, 0, 0, tzinfo=UTC),
        )

        user = AuthenticatedUser(
            sub=str(traveler), email=f"{traveler}@x.com", role="authenticated", claims={}
        )
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.session_id == traveler_sid
    finally:
        await _cleanup(client_ids=(client_id,), owner=owner)
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": traveler})
        finally:
            await engine.dispose()


@integration
@pytest.mark.asyncio
async def test_onboarding_session_ignores_itinerary_pinned(
    db_session: AsyncSession,
) -> None:
    """Basecamp resolves the BASECAMP (unpinned) session, not a newer itinerary one.

    Regression (M006/PS7): after PS2 scoped session reuse to the itinerary, a
    traveler chatting with Artemis on a trip opens a *newer* itinerary-pinned
    session. Without the ``itinerary_id IS NULL`` filter the basecamp rail picked
    that up and showed "your chat from the itinerary" instead of the basecamp
    thread.
    """
    from app.auth import AuthenticatedUser
    from app.routers.me import get_my_onboarding_session_endpoint

    owner = uuid.uuid4()
    traveler = uuid.uuid4()
    for uid in (owner, traveler):
        await db_session.execute(
            text(
                """
                insert into auth.users (id, email, aud, role, instance_id)
                values (:id, :email, 'authenticated', 'authenticated',
                        '00000000-0000-0000-0000-000000000000')
                """
            ),
            {"id": uid, "email": f"{uid}@x.com"},
        )
    await db_session.commit()

    client_id = await _insert_linked_client(db_session, owner, traveler, "pinned-traveler")
    trip = await insert_itinerary(db_session, title="Kyoto", client_id=client_id)
    try:
        basecamp_sid = await _insert_session(
            db_session,
            client_id=client_id,
            audience="traveler",
            started_at=datetime(2026, 6, 29, 2, 0, 0, tzinfo=UTC),
        )
        # Itinerary-pinned session is NEWER — it would win a naive most-recent query.
        await _insert_session(
            db_session,
            client_id=client_id,
            audience="traveler",
            started_at=datetime(2026, 6, 29, 5, 0, 0, tzinfo=UTC),
            itinerary_id=trip,
        )

        user = AuthenticatedUser(
            sub=str(traveler), email=f"{traveler}@x.com", role="authenticated", claims={}
        )
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.session_id == basecamp_sid
    finally:
        await _cleanup(trip, client_ids=(client_id,), owner=owner)
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": traveler})
        finally:
            await engine.dispose()


def test_evaluate_onboarding_rule() -> None:
    """The one swappable onboarding rule, in isolation (ONB-2A).

    Today: satisfied by two profile facts. When the bar moves again this test
    moves with the rule — and it's the only place besides the rule body that
    needs to; the nudge + milestone callers read the bool and don't change.
    """
    from app.routers.me import evaluate_onboarding

    assert evaluate_onboarding(profile_fact_count=0) is False
    assert evaluate_onboarding(profile_fact_count=1) is False
    assert evaluate_onboarding(profile_fact_count=2) is True
    assert evaluate_onboarding(profile_fact_count=3) is True


@integration
@pytest.mark.asyncio
async def test_onboarding_session_reports_onboarding_complete(
    db_session: AsyncSession,
) -> None:
    """``onboarding_complete`` drives the nudge + milestone card (ONB-2A).

    False until the onboarding rule is satisfied — today, two non-redacted
    ``profile_facts`` rows. A redacted (soft-deleted) fact must not count,
    matching the active-fact filter used elsewhere.
    """
    from app.auth import AuthenticatedUser
    from app.routers.me import get_my_onboarding_session_endpoint

    owner = uuid.uuid4()
    traveler = uuid.uuid4()
    for uid in (owner, traveler):
        await db_session.execute(
            text(
                """
                insert into auth.users (id, email, aud, role, instance_id)
                values (:id, :email, 'authenticated', 'authenticated',
                        '00000000-0000-0000-0000-000000000000')
                """
            ),
            {"id": uid, "email": f"{uid}@x.com"},
        )
    await db_session.commit()

    client_id = await _insert_linked_client(db_session, owner, traveler, "facts-traveler")
    user = AuthenticatedUser(
        sub=str(traveler), email=f"{traveler}@x.com", role="authenticated", claims={}
    )
    try:
        # No facts yet — the traveler has told us nothing.
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.onboarding_complete is False

        # A redacted fact does not count.
        await _insert_profile_fact(
            db_session, client_id=client_id, recorded_by=traveler, redacted=True
        )
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.onboarding_complete is False

        # One live fact is not enough — today's rule needs two.
        await _insert_profile_fact(
            db_session, client_id=client_id, recorded_by=traveler, redacted=False
        )
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.onboarding_complete is False

        # A second live fact satisfies today's rule.
        await _insert_profile_fact(
            db_session, client_id=client_id, recorded_by=traveler, redacted=False
        )
        resp = await get_my_onboarding_session_endpoint(user=user, session=db_session)
        assert resp.onboarding_complete is True
    finally:
        # profile_facts cascade-delete with the client (FK ondelete CASCADE).
        await _cleanup(client_ids=(client_id,), owner=owner)
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": traveler})
        finally:
            await engine.dispose()
