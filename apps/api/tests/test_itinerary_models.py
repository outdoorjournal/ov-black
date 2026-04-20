"""Tests for the itinerary graph models (0002_itinerary_graph.sql).

Two layers:
  1. Pure-Python guard — asserts the SAEnum create_type flag is False on every
     new enum so we don't regress D003 (Supabase CLI owns DDL, SQLAlchemy
     must never CREATE TYPE).
  2. Integration round-trip against a locally-running Supabase Postgres. Gated
     by _supabase_running() so dev machines without Docker skip cleanly.
     Inserts an itinerary + subgraph parent + child + alternative_to edge,
     asserts rows read back with the expected enum types and jsonb content,
     and exercises the nodes_provenance_complete + edges_no_self_loop
     constraints as negative tests.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    Edge,
    EdgeHistory,
    EdgeType,
    Itinerary,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
)
from app.models.itinerary import (
    edge_type_enum,
    node_status_enum,
    node_type_enum,
)

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


def test_saenum_create_type_is_false_for_all_graph_enums() -> None:
    """Regression guard for D003: Supabase CLI owns DDL — SQLAlchemy never
    emits CREATE TYPE for the three new Postgres enums.
    """
    for sa_enum in (node_type_enum, node_status_enum, edge_type_enum):
        assert sa_enum.create_type is False, (
            f"Postgres ENUM {sa_enum.name!r} must have create_type=False so "
            "SQLAlchemy does not try to CREATE TYPE against the DB "
            "(the migration owns that)."
        )
        assert sa_enum.schema == "public"


def test_node_type_enum_values_match_migration() -> None:
    """Python enum values must be byte-identical to the Postgres enum so the
    values_callable lambda rendering in SAEnum round-trips correctly.
    """
    assert {m.value for m in NodeType} == {
        "destination",
        "flight",
        "hotel",
        "experience",
        "meal",
        "transit",
        "free_time",
        "note",
    }
    assert {m.value for m in NodeStatus} == {
        "idea",
        "proposed",
        "approved",
        "booked",
        "confirmed",
        "discarded",
    }
    assert {m.value for m in EdgeType} == {
        "follows",
        "alternative_to",
        "connected_by",
        "requires",
        "grouped_with",
    }


# ── Integration tests (gated on local Supabase) ────────────────────────────

integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase Postgres (127.0.0.1:54322) not running — `supabase start` first",
)


@pytest_asyncio.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    # Cascade on itineraries deletes nodes + edges; history tables are
    # append-only and carry itinerary_id so we clear them explicitly.
    await session.execute(
        text("delete from public.edge_history where itinerary_id = :i"),
        {"i": itinerary_id},
    )
    await session.execute(
        text("delete from public.node_history where itinerary_id = :i"),
        {"i": itinerary_id},
    )
    await session.execute(
        text("delete from public.itineraries where id = :i"), {"i": itinerary_id}
    )
    await session.commit()


@integration
@pytest.mark.asyncio
async def test_itinerary_graph_round_trip(session: AsyncSession) -> None:
    itinerary_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    alt_id = uuid.uuid4()
    edge_id = uuid.uuid4()

    try:
        itinerary = Itinerary(id=itinerary_id, title="Como")
        session.add(itinerary)
        await session.flush()

        parent = Node(
            id=parent_id,
            itinerary_id=itinerary_id,
            type=NodeType.experience,
            status=NodeStatus.proposed,
            title="Amalfi multi-stop",
            source="ov",
            source_id="trip-123",
            metadata_={"location": {"country_code": "IT"}, "priority": "must_do"},
        )
        child = Node(
            id=child_id,
            itinerary_id=itinerary_id,
            parent_subgraph_id=parent_id,
            type=NodeType.meal,
            status=NodeStatus.idea,
            title="Lunch at Le Sirenuse",
            metadata_={"content": {"description": "seaside lunch"}},
        )
        alt = Node(
            id=alt_id,
            itinerary_id=itinerary_id,
            parent_subgraph_id=parent_id,
            type=NodeType.meal,
            status=NodeStatus.idea,
            title="Lunch at La Sponda (alternative)",
        )
        session.add_all([parent, child, alt])
        await session.flush()

        edge = Edge(
            id=edge_id,
            itinerary_id=itinerary_id,
            from_node_id=child_id,
            to_node_id=alt_id,
            type=EdgeType.alternative_to,
            metadata_={"reason": "client preference split"},
        )
        session.add(edge)

        # History row written alongside the mutation (service layer would do
        # this in real code; here we exercise the table + JSONB typing).
        history = NodeHistory(
            node_id=child_id,
            itinerary_id=itinerary_id,
            op="insert",
            actor_kind="system",
            before=None,
            after={"title": "Lunch at Le Sirenuse"},
        )
        edge_hist = EdgeHistory(
            edge_id=edge_id,
            itinerary_id=itinerary_id,
            op="insert",
            actor_kind="system",
            after={"type": "alternative_to"},
        )
        session.add_all([history, edge_hist])
        await session.commit()

        fetched_parent = (
            await session.execute(select(Node).where(Node.id == parent_id))
        ).scalar_one()
        assert fetched_parent.type is NodeType.experience
        assert fetched_parent.status is NodeStatus.proposed
        assert fetched_parent.source == "ov"
        assert fetched_parent.source_id == "trip-123"
        assert fetched_parent.metadata_ == {
            "location": {"country_code": "IT"},
            "priority": "must_do",
        }
        assert isinstance(fetched_parent.created_at, datetime)
        assert fetched_parent.created_at.tzinfo is not None

        fetched_child = (
            await session.execute(select(Node).where(Node.id == child_id))
        ).scalar_one()
        assert fetched_child.parent_subgraph_id == parent_id
        assert fetched_child.type is NodeType.meal

        fetched_edge = (
            await session.execute(select(Edge).where(Edge.id == edge_id))
        ).scalar_one()
        assert fetched_edge.type is EdgeType.alternative_to
        assert fetched_edge.metadata_ == {"reason": "client preference split"}

        fetched_hist = (
            await session.execute(
                select(NodeHistory).where(NodeHistory.node_id == child_id)
            )
        ).scalar_one()
        assert fetched_hist.op == "insert"
        assert fetched_hist.actor_kind == "system"
        assert fetched_hist.after == {"title": "Lunch at Le Sirenuse"}
        assert fetched_hist.before is None
    finally:
        await _cleanup(session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_nodes_provenance_complete_rejects_half_sourced_node(
    session: AsyncSession,
) -> None:
    """INSERT of a node with source set but source_id NULL must raise
    IntegrityError naming nodes_provenance_complete (R020 at schema level).
    """
    itinerary_id = uuid.uuid4()
    try:
        session.add(Itinerary(id=itinerary_id, title="neg test"))
        await session.flush()

        session.add(
            Node(
                itinerary_id=itinerary_id,
                type=NodeType.experience,
                source="ov",
                source_id=None,
            )
        )
        with pytest.raises(IntegrityError) as excinfo:
            await session.flush()
        assert "nodes_provenance_complete" in str(excinfo.value)
    finally:
        await session.rollback()
        await _cleanup(session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_edges_no_self_loop_rejects_self_edge(
    session: AsyncSession,
) -> None:
    """INSERT of an edge with from_node_id == to_node_id must raise
    IntegrityError naming edges_no_self_loop.
    """
    itinerary_id = uuid.uuid4()
    node_id = uuid.uuid4()
    try:
        session.add(Itinerary(id=itinerary_id, title="neg test 2"))
        await session.flush()
        session.add(
            Node(
                id=node_id,
                itinerary_id=itinerary_id,
                type=NodeType.note,
            )
        )
        await session.flush()

        session.add(
            Edge(
                itinerary_id=itinerary_id,
                from_node_id=node_id,
                to_node_id=node_id,
                type=EdgeType.follows,
            )
        )
        with pytest.raises(IntegrityError) as excinfo:
            await session.flush()
        assert "edges_no_self_loop" in str(excinfo.value)
    finally:
        await session.rollback()
        await _cleanup(session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_rls_enabled_on_all_graph_tables(session: AsyncSession) -> None:
    """Deny-by-default posture: RLS on, zero policies, matches invites in 0001."""
    rows = (
        await session.execute(
            text(
                """
                select tablename, rowsecurity
                  from pg_tables
                 where schemaname = 'public'
                   and tablename in (
                       'itineraries', 'nodes', 'edges',
                       'node_history', 'edge_history'
                   )
                 order by tablename
                """
            )
        )
    ).all()
    rls = {tbl: enabled for tbl, enabled in rows}
    assert rls == {
        "itineraries": True,
        "nodes": True,
        "edges": True,
        "node_history": True,
        "edge_history": True,
    }

    count = (
        await session.execute(
            text(
                """
                select count(*)
                  from pg_policies
                 where schemaname = 'public'
                   and tablename in (
                       'itineraries', 'nodes', 'edges',
                       'node_history', 'edge_history'
                   )
                """
            )
        )
    ).scalar_one()
    assert count == 0, "Graph tables must ship with zero policies (deny-by-default)"


def test_node_status_includes_discarded() -> None:
    """S07: the discarded enum value must be present on NodeStatus so pin /
    keep / discard can round-trip (pin → approved, keep → proposed,
    discard → discarded). Guards the SQLAlchemy side of migration 0005.
    """
    assert NodeStatus.discarded == "discarded"
    assert "discarded" in {m.value for m in NodeStatus}


@integration
@pytest.mark.asyncio
async def test_update_node_discarded_round_trips_through_history(
    session: AsyncSession,
) -> None:
    """S07: update_node with status=discarded must persist and land in
    node_history with after.status == 'discarded' (no new logging surface;
    reuses the existing itinerary.mutate op=update_node trail).
    """
    # Import here so the module-level collection doesn't pull service deps
    # when the integration gate skips these tests.
    from app.services.itineraries import (
        ActorContext,
        ActorKind,
        update_node,
    )

    itinerary_id = uuid.uuid4()
    node_id = uuid.uuid4()
    try:
        session.add(Itinerary(id=itinerary_id, title="S07 discarded round-trip"))
        await session.flush()

        node = Node(
            id=node_id,
            itinerary_id=itinerary_id,
            type=NodeType.experience,
            status=NodeStatus.proposed,
            title="OV experience card",
            source="ov",
            source_id="exp-42",
        )
        session.add(node)
        await session.commit()

        actor = ActorContext(user_id=None, kind=ActorKind.AGENT, actor_id="test-agent")
        result = await update_node(
            session,
            actor,
            itinerary_id=itinerary_id,
            node_id=node_id,
            status=NodeStatus.discarded,
        )
        assert isinstance(result, Node)
        assert result.status is NodeStatus.discarded

        fetched = (
            await session.execute(select(Node).where(Node.id == node_id))
        ).scalar_one()
        assert fetched.status is NodeStatus.discarded

        history_rows = (
            await session.execute(
                select(NodeHistory)
                .where(NodeHistory.node_id == node_id)
                .order_by(NodeHistory.id)
            )
        ).scalars().all()
        # update_node writes one history row for the status transition.
        assert len(history_rows) == 1
        hist = history_rows[0]
        assert hist.op == "update"
        assert hist.before is not None
        assert hist.before["status"] == "proposed"
        assert hist.after is not None
        assert hist.after["status"] == "discarded"
    finally:
        await _cleanup(session, itinerary_id)
