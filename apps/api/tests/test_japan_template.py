"""Tests for the Japan template builder + the /demos/japan router (Phase 4).

Two layers:

1. **Builder** — confirms the find-or-create pattern is idempotent and
   that a fresh build populates the right node + edge counts derived
   from the seed-data Japan fixture.
2. **Router** — POST /demos/japan happy path + auth/ownership gates.
   Real-DB integration so the end-to-end story (advisor calls demo
   endpoint → fresh itinerary lands in their client's account) is
   exercised through every layer.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.main import app as fastapi_app
from app.models import (
    CardTemplate,
    Edge,
    Itinerary,
    Node,
    TemplateEdge,
    TemplateNode,
)
from app.seed_data.japan_itinerary import all_items
from app.services.japan_template import (
    JAPAN_TEMPLATE_SLUG,
    build_japan_template,
)
from app.services.timeline import linearize

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator


LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


# ── Setup helpers ─────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> "AsyncIterator[AsyncSession]":
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(
        bind=engine, expire_on_commit=False, class_=AsyncSession
    )
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _delete_japan_template_if_exists() -> None:
    """Remove the Japan template + cascade everything that points at it.
    Some tests start with the template already present from earlier
    runs; this gives the builder a clean slate.
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "delete from public.card_templates where slug = :slug"
                ),
                {"slug": JAPAN_TEMPLATE_SLUG},
            )
    finally:
        await engine.dispose()


async def _delete_itinerary(itinerary_id: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "delete from public.node_history where itinerary_id = :i"
                ),
                {"i": itinerary_id},
            )
            await conn.execute(
                text(
                    "delete from public.edge_history where itinerary_id = :i"
                ),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
    finally:
        await engine.dispose()


# ── Builder tests ────────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_build_japan_template_creates_node_per_fixture_item(
    db_session: AsyncSession,
) -> None:
    """A fresh build creates one template_node per fixture item.

    Edge count = within-day follows + day-to-day bridges. Within each
    day there are (len-1) follows; bridges across day boundaries add
    (num_days - 1) more.
    """
    await _delete_japan_template_if_exists()
    template: CardTemplate | None = None
    try:
        template = await build_japan_template(db_session)

        item_count = len(all_items())
        nodes = (
            await db_session.execute(
                select(func.count(TemplateNode.id)).where(
                    TemplateNode.template_id == template.id
                )
            )
        ).scalar_one()
        assert nodes == item_count

        edges = (
            await db_session.execute(
                select(func.count(TemplateEdge.id)).where(
                    TemplateEdge.template_id == template.id
                )
            )
        ).scalar_one()
        # Each day: (items_per_day - 1) follows; plus (num_days - 1)
        # bridges between days. The fixture has at least 4 days each
        # with multiple items; specific check is left loose so adding
        # items to the fixture doesn't break the test.
        assert edges >= item_count - 1, (
            "Edge count must connect every node into a single chain"
        )
    finally:
        if template is not None:
            await _delete_japan_template_if_exists()


@integration
@pytest.mark.asyncio
async def test_build_japan_template_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Re-running the builder doesn't duplicate nodes/edges."""
    await _delete_japan_template_if_exists()
    try:
        first = await build_japan_template(db_session)
        first_node_count = (
            await db_session.execute(
                select(func.count(TemplateNode.id)).where(
                    TemplateNode.template_id == first.id
                )
            )
        ).scalar_one()
        first_edge_count = (
            await db_session.execute(
                select(func.count(TemplateEdge.id)).where(
                    TemplateEdge.template_id == first.id
                )
            )
        ).scalar_one()

        second = await build_japan_template(db_session)
        assert second.id == first.id

        second_node_count = (
            await db_session.execute(
                select(func.count(TemplateNode.id)).where(
                    TemplateNode.template_id == second.id
                )
            )
        ).scalar_one()
        second_edge_count = (
            await db_session.execute(
                select(func.count(TemplateEdge.id)).where(
                    TemplateEdge.template_id == second.id
                )
            )
        ).scalar_one()
        assert second_node_count == first_node_count
        assert second_edge_count == first_edge_count

        # Every built template node stamps its local UTC offset (JST → 540)
        # in metadata so the read side can re-emit starts_at in wall-clock.
        scheduled = (
            await db_session.execute(
                select(TemplateNode.metadata_).where(
                    TemplateNode.template_id == first.id,
                    TemplateNode.starts_at_offset_minutes.is_not(None),
                )
            )
        ).scalars().all()
        assert scheduled  # the fixture has scheduled items
        assert all(m.get("tz_offset_minutes") == 540 for m in scheduled)
    finally:
        await _delete_japan_template_if_exists()


@integration
@pytest.mark.asyncio
async def test_japan_instantiation_linearizes_chronologically(
    db_session: AsyncSession,
) -> None:
    """End-to-end: build, instantiate, and linearize. The result must
    walk the seed-data items in their declared order — proves the
    template anchors offsets correctly and that the linearization
    service handles instantiated nodes the same way as raw inserts.
    """
    await _delete_japan_template_if_exists()
    itinerary: Itinerary | None = None
    try:
        from app.services.templates import instantiate_template

        template = await build_japan_template(db_session)
        trip_start = datetime(
            2030, 5, 1, 0, 0, tzinfo=timezone(timedelta(hours=9))
        )
        itinerary = await instantiate_template(
            db_session,
            template=template,
            client_id=None,
            trip_start_at=trip_start,
        )

        view = await linearize(db_session, itinerary_id=itinerary.id)
        actual_titles = [c.title for c in view.cards]
        expected_titles = [item.title for item in all_items()]
        assert actual_titles == expected_titles
        # Every card carries the lineage snapshot.
        for c in view.cards:
            # Re-fetch to inspect lineage columns (Card dataclass doesn't
            # surface them).
            row = (
                await db_session.execute(
                    text(
                        """
                        select template_id, template_version, metadata
                          from public.nodes
                         where id = :id
                        """
                    ),
                    {"id": c.node_id},
                )
            ).mappings().one()
            assert row["template_id"] == template.id
            assert row["template_version"] == template.version
            # The per-node tz offset was copied from the template metadata
            # onto the instantiated node (JST → 540).
            assert row["metadata"].get("tz_offset_minutes") == 540
    finally:
        if itinerary is not None:
            await _delete_itinerary(itinerary.id)
        await _delete_japan_template_if_exists()


# ── Router tests ─────────────────────────────────────────────────────


@pytest.fixture()
def http_client() -> "Iterator[TestClient]":
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def advisor_sub() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def auth_headers(
    make_token: "Callable[..., str]",
    advisor_sub: uuid.UUID,
) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_sub))}"}


@pytest.fixture()
def override_require_advisor(
    advisor_sub: uuid.UUID,
) -> "Iterator[uuid.UUID]":
    async def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            sub=str(advisor_sub),
            email="advisor@example.com",
            role="authenticated",
            claims={"sub": str(advisor_sub)},
        )

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield advisor_sub
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def override_require_advisor_rejects() -> "Iterator[None]":
    async def _dep() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


def test_demos_japan_rejects_non_advisor(
    http_client: TestClient,
    auth_headers: dict[str, str],
    override_require_advisor_rejects: None,
) -> None:
    """Without advisor role the endpoint is gated at the dependency."""
    _ = override_require_advisor_rejects
    resp = http_client.post(
        "/demos/japan",
        json={"client_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 403


def _run_async(coro_factory: "Callable[[], object]") -> object:
    """Run an async coroutine factory inside a fresh event loop.

    Each call creates + disposes its own engine inside one asyncio.run
    so SQLAlchemy's async cleanup doesn't trip over a closed loop. The
    factory pattern lets the caller construct the coroutine inside the
    new loop, which is required because async generators / sessions
    bind to the loop active at construction.
    """
    import asyncio

    async def _wrapper() -> object:
        engine = create_async_engine(
            LOCAL_DB_URL, pool_pre_ping=True, future=True
        )
        try:
            return await coro_factory(engine)
        finally:
            await engine.dispose()

    return asyncio.run(_wrapper())


@integration
def test_demos_japan_404_for_unknown_client(
    http_client: TestClient,
    auth_headers: dict[str, str],
    override_require_advisor: uuid.UUID,
) -> None:
    """Client not in the DB → 404, not a confusing 500."""
    _ = override_require_advisor
    resp = http_client.post(
        "/demos/japan",
        json={"client_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"


@integration
def test_demos_japan_403_when_client_owned_by_other_advisor(
    http_client: TestClient,
    auth_headers: dict[str, str],
    override_require_advisor: uuid.UUID,
) -> None:
    """Stops one advisor seeding into another's client."""
    advisor_sub = override_require_advisor

    other_advisor = uuid.uuid4()
    client_id = uuid.uuid4()
    auth_user_id = uuid.uuid4()

    async def _setup(engine: object) -> None:
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            for uid in (other_advisor, auth_user_id, advisor_sub):
                await conn.execute(
                    text(
                        """
                        insert into auth.users (id, email)
                        values (:id, :email)
                        on conflict (id) do nothing
                        """
                    ),
                    {"id": uid, "email": f"{uid}@test.example"},
                )
            await conn.execute(
                text(
                    """
                    insert into public.clients (
                        id, full_name, email, owner_id, auth_user_id
                    ) values (
                        :id, 'someone else',
                        'someone-else@test.example',
                        :other, :auth
                    )
                    """
                ),
                {
                    "id": client_id,
                    "other": other_advisor,
                    "auth": auth_user_id,
                },
            )

    async def _cleanup(engine: object) -> None:
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                text("delete from public.clients where id = :id"),
                {"id": client_id},
            )
            for uid in (other_advisor, auth_user_id, advisor_sub):
                await conn.execute(
                    text("delete from auth.users where id = :id"),
                    {"id": uid},
                )

    try:
        _run_async(_setup)
        resp = http_client.post(
            "/demos/japan",
            json={"client_id": str(client_id)},
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "client_not_owned"
    finally:
        _run_async(_cleanup)


@integration
def test_demos_japan_happy_path_creates_itinerary(
    http_client: TestClient,
    auth_headers: dict[str, str],
    override_require_advisor: uuid.UUID,
) -> None:
    """Advisor + their own client + Japan template → fresh itinerary
    materialized with the seed-data node count.
    """
    advisor_sub = override_require_advisor

    client_id = uuid.uuid4()
    auth_user_id = uuid.uuid4()

    async def _setup(engine: object) -> None:
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            for uid in (advisor_sub, auth_user_id):
                await conn.execute(
                    text(
                        """
                        insert into auth.users (id, email)
                        values (:id, :email)
                        on conflict (id) do nothing
                        """
                    ),
                    {"id": uid, "email": f"{uid}@test.example"},
                )
            await conn.execute(
                text(
                    """
                    insert into public.clients (
                        id, full_name, email, owner_id, auth_user_id
                    ) values (
                        :id, 'demo client',
                        'demo-client@test.example',
                        :owner, :auth
                    )
                    """
                ),
                {
                    "id": client_id,
                    "owner": advisor_sub,
                    "auth": auth_user_id,
                },
            )
            # Clean any prior Japan template so the builder runs fresh.
            await conn.execute(
                text(
                    "delete from public.card_templates where slug = :s"
                ),
                {"s": JAPAN_TEMPLATE_SLUG},
            )

    async def _verify_persisted(engine: object, itinerary_id: uuid.UUID) -> None:
        maker = async_sessionmaker(
            bind=engine,  # type: ignore[arg-type]
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with maker() as s:
            row = (
                await s.execute(
                    select(Itinerary).where(Itinerary.id == itinerary_id)
                )
            ).scalar_one()
            assert row.client_id == client_id
            assert row.created_by == advisor_sub
            lineage = (
                await s.execute(
                    text(
                        """
                        select count(*) from public.nodes
                        where itinerary_id = :i
                          and template_id is not null
                          and template_version is not null
                        """
                    ),
                    {"i": itinerary_id},
                )
            ).scalar_one()
            assert lineage == len(all_items())
            edges = (
                await s.execute(
                    select(func.count(Edge.id)).where(
                        Edge.itinerary_id == itinerary_id
                    )
                )
            ).scalar_one()
            assert edges >= len(all_items()) - 1

    async def _cleanup(
        engine: object, itinerary_id: uuid.UUID | None
    ) -> None:
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            if itinerary_id is not None:
                await conn.execute(
                    text("delete from public.itineraries where id = :i"),
                    {"i": itinerary_id},
                )
            await conn.execute(
                text(
                    "delete from public.card_templates where slug = :s"
                ),
                {"s": JAPAN_TEMPLATE_SLUG},
            )
            await conn.execute(
                text("delete from public.clients where id = :id"),
                {"id": client_id},
            )
            for uid in (advisor_sub, auth_user_id):
                await conn.execute(
                    text("delete from auth.users where id = :id"),
                    {"id": uid},
                )

    itinerary_id: uuid.UUID | None = None
    try:
        _run_async(_setup)

        resp = http_client.post(
            "/demos/japan",
            json={"client_id": str(client_id)},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["template_slug"] == JAPAN_TEMPLATE_SLUG
        assert body["node_count"] == len(all_items())
        assert body["edge_count"] >= body["node_count"] - 1

        itinerary_id = uuid.UUID(body["itinerary_id"])
        _run_async(lambda eng: _verify_persisted(eng, itinerary_id))
    finally:
        _run_async(lambda eng: _cleanup(eng, itinerary_id))


def _ensure_node_imported(_x: Node | None = None) -> None:  # pragma: no cover
    """Keep the Node import flagged as used by static analysis (we need
    it for the lineage query above)."""
