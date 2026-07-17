"""Phase 5 (doc/itin-time.md): analysis becomes the feasibility surface.

Two halves:

* Unit — ``services.kernel_graph.kernel_graph_from_view`` assembles the pure
  kernel ``Graph`` from a served view: subgraph children excluded, flight
  provenance date-sensitive, ``min_gap_minutes`` picked off edge metadata.
* Integration — a real graph read produces kernel findings for the classic
  cases (the Detroit→Thessaloniki arrival-after-first-item flight, an
  overlap, a stale moved quote), serialized as ``GraphFindingResponse`` on
  the graph-read endpoint's ``findings`` field via ``_findings_for_view``.
"""

from __future__ import annotations

import socket
import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from app.kernel import analyze, relative
from app.models import EdgeType, ItineraryTimingKind, NodeStatus, NodeType
from app.routers.itineraries import _findings_for_view
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    GraphView,
    ItineraryError,
    SchedulePlacement,
    add_edge,
    add_node,
    create_itinerary,
    get_itinerary_graph,
    update_node,
)
from app.services.kernel_graph import kernel_graph_from_view
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

_OLYMPUS = {"lat": 40.0885, "lng": 22.3489}
_DTW = {"lat": 42.2143, "lng": -83.3544}
_SKG = {"lat": 40.5201, "lng": 22.9713}


# ── kernel_graph_from_view (unit) ───────────────────────────────────────────


def _out_node(
    node_id: str,
    *,
    node_type: NodeType = NodeType.experience,
    parent: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    kernel_schedule: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=hash(node_id) % (2**64)),
        parent_subgraph_id=uuid.UUID(int=hash(parent) % (2**64)) if parent else None,
        type=node_type,
        status=NodeStatus.pending,
        title=node_id,
        source=source,
        source_id="src-1" if source else None,
        metadata=metadata or {},
        needs_revalidation=False,
        kernel_schedule=kernel_schedule,
    )


def _view(nodes: list[SimpleNamespace], edges: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        itinerary=SimpleNamespace(anchor_date=date(2026, 8, 1)),
        nodes=nodes,
        edges=edges,
    )


def test_kernel_graph_excludes_subgraph_children_and_their_edges() -> None:
    parent = _out_node("parent")
    child = _out_node("child", parent="parent")
    edge = SimpleNamespace(
        id=uuid.uuid4(),
        from_node_id=parent.id,
        to_node_id=child.id,
        type=EdgeType.follows,
        metadata={},
    )
    graph = kernel_graph_from_view(_view([parent, child], [edge]))
    assert set(graph.nodes) == {str(parent.id)}
    assert graph.edges == {}
    assert graph.anchor_date == date(2026, 8, 1)


def test_kernel_graph_flight_provenance_is_date_sensitive() -> None:
    flight = _out_node("f", node_type=NodeType.flight, source="duffel")
    meal = _out_node("m", node_type=NodeType.meal, source="serp")
    graph = kernel_graph_from_view(_view([flight, meal], []))
    assert graph.nodes[str(flight.id)].provenance is not None
    assert graph.nodes[str(flight.id)].provenance.date_sensitive is True
    assert graph.nodes[str(meal.id)].provenance.date_sensitive is False


def test_kernel_graph_reads_min_gap_from_edge_metadata() -> None:
    a, b = _out_node("a"), _out_node("b")
    edge = SimpleNamespace(
        id=uuid.uuid4(),
        from_node_id=a.id,
        to_node_id=b.id,
        type=EdgeType.follows,
        metadata={"min_gap_minutes": 45},
    )
    graph = kernel_graph_from_view(_view([a, b], [edge]))
    assert next(iter(graph.edges.values())).min_gap_minutes == 45


def test_kernel_graph_schedules_ride_through() -> None:
    schedule = relative(2, __import__("datetime").time(9, 0), "Europe/Athens")
    node = _out_node("s", kernel_schedule=schedule)
    graph = kernel_graph_from_view(_view([node], []))
    assert graph.nodes[str(node.id)].schedule == schedule


# ── integration: graph read → findings ──────────────────────────────────────


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="kernel-phase5-test")


@pytest_asyncio.fixture
async def db_session() -> Any:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _cleanup(session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    from sqlalchemy import text

    await session.execute(text("delete from itineraries where id = :iid"), {"iid": itinerary_id})
    await session.commit()


@integration
async def test_late_outbound_produces_flight_infeasible_block(db_session: AsyncSession) -> None:
    """The Detroit→Thessaloniki regression, now a finding on the graph read."""
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase5-flight",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2026, 8, 14),
    )
    try:
        first = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Trip to Mount Olympus",
            starts_at="2026-08-14T15:00:00+03:00",
            duration_minutes=8640,
            metadata={"location": _OLYMPUS},
        )
        flight = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.flight,
            title="DTW → SKG",
            source="duffel",
            source_id="off_late",
            starts_at="2026-08-14T10:03:00-04:00",
            duration_minutes=1111,  # arrives 04:34 +03:00 on the 15th
            metadata={"from_location": _DTW, "to_location": _SKG},
        )
        assert not isinstance(first, ItineraryError)
        assert not isinstance(flight, ItineraryError)

        view = await get_itinerary_graph(db_session, itin.id)
        assert isinstance(view, GraphView)
        findings = analyze(kernel_graph_from_view(view))
        blocks = [f for f in findings if f.code == "flight_infeasible"]
        assert len(blocks) == 1
        assert blocks[0].severity == "block"
        assert set(blocks[0].node_ids) == {str(flight.id), str(first.id)}

        # And the router serialization carries the same judgement.
        responses = _findings_for_view(view)
        assert any(
            r.code == "flight_infeasible" and r.severity == "block" and flight.id in r.node_ids
            for r in responses
        )
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_overlap_and_stale_findings_on_graph_read(db_session: AsyncSession) -> None:
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase5-overlap",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2026, 8, 14),
    )
    try:
        lunch = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.meal,
            title="Long lunch",
            starts_at="2026-08-15T12:00:00+03:00",
            duration_minutes=120,
        )
        tour = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Old town tour",
            starts_at="2026-08-15T13:00:00+03:00",
            duration_minutes=90,
        )
        quote = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.flight,
            title="Quoted hop",
            source="duffel",
            source_id="off_1",
            starts_at="2026-08-20T10:00:00+03:00",
            duration_minutes=60,
        )
        assert not isinstance(lunch, ItineraryError)
        assert not isinstance(tour, ItineraryError)
        assert not isinstance(quote, ItineraryError)
        # Move the quoted flight → needs_revalidation → a stale info finding.
        moved = await update_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            node_id=quote.id,
            placement=SchedulePlacement(day_index=8, minute_of_day=10 * 60),
        )
        assert not isinstance(moved, ItineraryError)

        view = await get_itinerary_graph(db_session, itin.id)
        assert isinstance(view, GraphView)
        by_code = {f.code: f for f in _findings_for_view(view)}

        assert "overlap" in by_code
        assert by_code["overlap"].severity == "warn"
        assert {lunch.id, tour.id} == set(by_code["overlap"].node_ids)

        assert "stale" in by_code
        assert by_code["stale"].severity == "info"
        assert by_code["stale"].node_ids == [quote.id]
    finally:
        await _cleanup(db_session, itin.id)


@integration
async def test_alternatives_do_not_overlap_warn(db_session: AsyncSession) -> None:
    """Deliberate co-timing (alternative_to) is not a finding."""
    itin = await create_itinerary(
        db_session,
        _actor(),
        title="phase5-alt",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2026, 8, 14),
    )
    try:
        a = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Option A",
            starts_at="2026-08-15T10:00:00+03:00",
            duration_minutes=120,
        )
        b = await add_node(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            type=NodeType.experience,
            title="Option B",
            starts_at="2026-08-15T10:30:00+03:00",
            duration_minutes=120,
        )
        assert not isinstance(a, ItineraryError)
        assert not isinstance(b, ItineraryError)
        edge = await add_edge(
            db_session,
            _actor(),
            itinerary_id=itin.id,
            from_node_id=a.id,
            to_node_id=b.id,
            type=EdgeType.alternative_to,
        )
        assert not isinstance(edge, ItineraryError)

        view = await get_itinerary_graph(db_session, itin.id)
        assert isinstance(view, GraphView)
        assert all(f.code != "overlap" for f in _findings_for_view(view))
    finally:
        await _cleanup(db_session, itin.id)
