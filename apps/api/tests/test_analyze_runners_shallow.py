"""Shallow Analyze runner — structural findings on contrived graphs (B5).

Integration (gated on local Supabase): seeds small graphs via raw SQL and
asserts the runner surfaces the four structural concerns — time overlap,
cycles, missing-required fields on firmed-up nodes, and the fuzz count.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest_asyncio
from app.models import FindingSeverity
from app.services.analyze_runners import shallow
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import (
    LOCAL_DB_URL,
    insert_edge,
    insert_itinerary,
    insert_node,
    integration,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2024, 6, 20, h, m, tzinfo=UTC)


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


@integration
async def test_time_overlap_emits_warn(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    a = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Museum",
        starts_lower=_at(9),
        starts_upper=_at(11),
    )
    b = await insert_node(
        db_session,
        itinerary_id=iid,
        type="meal",
        title="Lunch",
        starts_lower=_at(10),
        starts_upper=_at(12),
    )
    findings, _nodes, _fuzz = await shallow.collect(db_session, itinerary_id=iid)
    time_findings = [f for f in findings if f.category == "time"]
    assert len(time_findings) == 1
    f = time_findings[0]
    assert f.severity is FindingSeverity.warn
    assert f.node_id == b
    assert f.evidence["overlapping_node_id"] == str(a)
    assert f.evidence["overlap_minutes"] == 60


@integration
async def test_no_overlap_when_sequential(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        starts_lower=_at(9),
        starts_upper=_at(10),
    )
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="meal",
        starts_lower=_at(10),
        starts_upper=_at(11),
    )
    findings, _n, _f = await shallow.collect(db_session, itinerary_id=iid)
    assert [f for f in findings if f.category == "time"] == []


@integration
async def test_cycle_emits_block(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    a = await insert_node(db_session, itinerary_id=iid, type="experience")
    b = await insert_node(db_session, itinerary_id=iid, type="experience")
    await insert_edge(db_session, itinerary_id=iid, from_node_id=a, to_node_id=b)
    await insert_edge(db_session, itinerary_id=iid, from_node_id=b, to_node_id=a)
    findings, _n, _f = await shallow.collect(db_session, itinerary_id=iid)
    cyclic = [f for f in findings if f.category == "cyclic"]
    assert len(cyclic) == 1
    assert cyclic[0].severity is FindingSeverity.block
    assert set(cyclic[0].evidence["cycle_node_ids"]) == {str(a), str(b)}


@integration
async def test_acyclic_chain_has_no_cycle_finding(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    a = await insert_node(db_session, itinerary_id=iid, type="experience")
    b = await insert_node(db_session, itinerary_id=iid, type="experience")
    c = await insert_node(db_session, itinerary_id=iid, type="experience")
    await insert_edge(db_session, itinerary_id=iid, from_node_id=a, to_node_id=b)
    await insert_edge(db_session, itinerary_id=iid, from_node_id=b, to_node_id=c)
    findings, _n, _f = await shallow.collect(db_session, itinerary_id=iid)
    assert [f for f in findings if f.category == "cyclic"] == []


@integration
async def test_missing_required_on_firmed_node(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Approved bookable node with neither a time nor a cost -> two suggestions.
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="flight",
        title="LHR-HND",
        status="approved",
    )
    findings, _n, _f = await shallow.collect(db_session, itinerary_id=iid)
    fields = {f.evidence["field_path"] for f in findings if f.category == "missing_required"}
    assert fields == {"starts_at", "cost_amount"}
    assert all(
        f.severity is FindingSeverity.suggest for f in findings if f.category == "missing_required"
    )


@integration
async def test_proposed_node_not_flagged_missing(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Still 'proposed' (not firmed) -> no missing_required nags.
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="flight",
        status="proposed",
    )
    findings, _n, _f = await shallow.collect(db_session, itinerary_id=iid)
    assert [f for f in findings if f.category == "missing_required"] == []


@integration
async def test_fuzz_count(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Fully specified (time + location) — not fuzzy.
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        starts_lower=_at(9),
        starts_upper=_at(10),
        lat=35.6,
        lng=139.7,
    )
    # No time, no location — fuzzy.
    await insert_node(db_session, itinerary_id=iid, type="experience")
    output = await shallow.run(db_session, itinerary_id=iid)
    assert output.node_count == 2
    assert output.fuzz_count == 1
