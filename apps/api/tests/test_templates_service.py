"""Tests for the card-template service (Phase 4).

Two layers:

1. **Pure-Python guards** — model surface is correctly re-exported,
   enums reused from itinerary (no fresh enum types, per D003).
2. **Integration** — gated on local Supabase. Covers find-or-create
   idempotency, subgraph authoring, and the instantiation path that
   copies a template into a fresh itinerary while stamping the
   template lineage snapshot on every new node.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from app.models import (
    CardTemplate,
    EdgeType,
    Node,
    NodeType,
    TemplateEdge,
    TemplateNode,
)
from app.services.templates import (
    add_template_edge,
    add_template_node,
    find_or_create_template,
    has_subgraph,
    instantiate_template,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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


# ── Pure-Python guards ────────────────────────────────────────────────


def test_template_models_export_from_models_package() -> None:
    """The Phase 4 ORM types must be importable from `app.models` so
    callers don't need to reach into submodules.
    """
    from app import models

    assert models.CardTemplate is CardTemplate
    assert models.TemplateNode is TemplateNode
    assert models.TemplateEdge is TemplateEdge


def test_template_classes_reuse_node_type_enum() -> None:
    """TemplateNode.type must reference the same Postgres enum as
    Node.type — otherwise SQLAlchemy would try to CREATE TYPE for a
    duplicate definition (D003 violation).
    """
    from app.models.itinerary import node_type_enum

    type_col = TemplateNode.__table__.c.type
    assert type_col.type is node_type_enum


# ── Integration setup ────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _delete_template(template_id: uuid.UUID) -> None:
    """Cascading delete on a fresh engine — template_nodes / template_edges
    are removed by the FK cascade. Instantiated nodes lose the template_id
    via ON DELETE SET NULL but otherwise survive; the test cleanup target
    is the template itself.
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.card_templates where id = :id"),
                {"id": template_id},
            )
    finally:
        await engine.dispose()


async def _delete_itinerary(itinerary_id: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.node_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.edge_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
    finally:
        await engine.dispose()


# ── Integration tests ────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_find_or_create_template_is_idempotent(
    db_session: AsyncSession,
) -> None:
    slug = f"phase4-test-{uuid.uuid4().hex[:8]}"
    try:
        first, created_first = await find_or_create_template(db_session, slug=slug, name="first")
        assert created_first is True
        second, created_second = await find_or_create_template(
            db_session, slug=slug, name="not used"
        )
        assert created_second is False
        # Same row, original name preserved (find_or_create does not
        # overwrite once a row exists).
        assert second.id == first.id
        assert second.name == "first"
    finally:
        await _delete_template(first.id)


@integration
@pytest.mark.asyncio
async def test_template_subgraph_authoring_round_trips(
    db_session: AsyncSession,
) -> None:
    slug = f"phase4-author-{uuid.uuid4().hex[:8]}"
    template, _ = await find_or_create_template(db_session, slug=slug, name="authoring round-trip")
    try:
        n_a = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.experience,
            title="A",
            starts_at_offset_minutes=540,  # 09:00 from anchor
            duration_minutes=60,
        )
        n_b = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.meal,
            title="B",
            starts_at_offset_minutes=720,  # 12:00 from anchor
            duration_minutes=90,
        )
        await add_template_edge(
            db_session,
            template_id=template.id,
            from_template_node_id=n_a.id,
            to_template_node_id=n_b.id,
            type=EdgeType.follows,
        )
        await db_session.commit()

        assert await has_subgraph(db_session, template_id=template.id) is True

        nodes = (
            (
                await db_session.execute(
                    select(TemplateNode).where(TemplateNode.template_id == template.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(nodes) == 2
        edges = (
            (
                await db_session.execute(
                    select(TemplateEdge).where(TemplateEdge.template_id == template.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(edges) == 1
        assert edges[0].type is EdgeType.follows
    finally:
        await _delete_template(template.id)


@integration
@pytest.mark.asyncio
async def test_instantiation_anchors_offsets_and_snapshots_lineage(
    db_session: AsyncSession,
) -> None:
    """Three-node template instantiates into a fresh itinerary with
    absolute starts_at values + lineage snapshots on every node.
    """
    slug = f"phase4-instantiate-{uuid.uuid4().hex[:8]}"
    template, _ = await find_or_create_template(db_session, slug=slug, name="instantiation test")
    itinerary_id: uuid.UUID | None = None
    try:
        # 09:00 (offset 540) → 60 min experience
        # 12:00 (offset 720) → 90 min meal
        # 21:00 (offset 1260) → 540 min hotel
        n_morning = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.experience,
            title="morning",
            starts_at_offset_minutes=540,
            duration_minutes=60,
        )
        n_lunch = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.meal,
            title="lunch",
            starts_at_offset_minutes=720,
            duration_minutes=90,
        )
        n_hotel = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.hotel,
            title="hotel",
            starts_at_offset_minutes=1260,
            duration_minutes=540,
        )
        await add_template_edge(
            db_session,
            template_id=template.id,
            from_template_node_id=n_morning.id,
            to_template_node_id=n_lunch.id,
            type=EdgeType.follows,
        )
        await add_template_edge(
            db_session,
            template_id=template.id,
            from_template_node_id=n_lunch.id,
            to_template_node_id=n_hotel.id,
            type=EdgeType.follows,
        )
        await db_session.commit()

        trip_start = datetime(2030, 5, 1, 0, 0, tzinfo=timezone(timedelta(hours=9)))
        itinerary = await instantiate_template(
            db_session,
            template=template,
            client_id=None,
            trip_start_at=trip_start,
            title="Demo Day Trip",
        )
        itinerary_id = itinerary.id
        assert itinerary.title == "Demo Day Trip"
        assert itinerary.client_id is None

        # Pull the instantiated nodes back; assert the lineage snapshot
        # AND the tstzrange lower bound matches trip_start + offset.
        rows = (
            (
                await db_session.execute(
                    text(
                        """
                    select id, title, template_id, template_node_id,
                           template_version,
                           lower(starts_at) as lo
                    from public.nodes
                    where itinerary_id = :iid
                    order by lower(starts_at) asc
                    """
                    ),
                    {"iid": itinerary.id},
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 3
        assert [r["title"] for r in rows] == ["morning", "lunch", "hotel"]
        for r in rows:
            assert r["template_id"] == template.id
            assert r["template_version"] == template.version
            assert r["template_node_id"] is not None
        # 09:00 lower == trip_start + 540 min
        assert rows[0]["lo"] == trip_start + timedelta(minutes=540)
        assert rows[1]["lo"] == trip_start + timedelta(minutes=720)
        assert rows[2]["lo"] == trip_start + timedelta(minutes=1260)
    finally:
        if itinerary_id is not None:
            await _delete_itinerary(itinerary_id)
        await _delete_template(template.id)


@integration
@pytest.mark.asyncio
async def test_instantiation_preserves_parent_subgraph_links(
    db_session: AsyncSession,
) -> None:
    """A template_node with parent_id remaps to the new node's
    parent_subgraph_id at instantiation. Tests the topological order
    (parents always come before children).
    """
    slug = f"phase4-parent-{uuid.uuid4().hex[:8]}"
    template, _ = await find_or_create_template(db_session, slug=slug, name="parent test")
    itinerary_id: uuid.UUID | None = None
    try:
        parent = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.destination,
            title="Tokyo container",
            starts_at_offset_minutes=0,
            duration_minutes=60,
        )
        child = await add_template_node(
            db_session,
            template_id=template.id,
            type=NodeType.experience,
            title="child inside Tokyo",
            parent_id=parent.id,
            starts_at_offset_minutes=120,
            duration_minutes=60,
        )
        await db_session.commit()

        itinerary = await instantiate_template(
            db_session,
            template=template,
            client_id=None,
            trip_start_at=datetime(2030, 6, 1, tzinfo=UTC),
            title="parent-child instantiation",
        )
        itinerary_id = itinerary.id

        # Find the child by title; assert its parent_subgraph_id points
        # to the freshly-inserted parent (NOT the template_node id).
        child_row = (
            await db_session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary.id,
                    Node.title == "child inside Tokyo",
                )
            )
        ).scalar_one()
        parent_row = (
            await db_session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary.id,
                    Node.title == "Tokyo container",
                )
            )
        ).scalar_one()
        assert child_row.parent_subgraph_id == parent_row.id
        assert child_row.template_node_id == child.id
        assert parent_row.template_node_id == parent.id
    finally:
        if itinerary_id is not None:
            await _delete_itinerary(itinerary_id)
        await _delete_template(template.id)
