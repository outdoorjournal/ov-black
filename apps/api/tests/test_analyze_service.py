"""Analyze service lifecycle (Phase 5 / B5).

Integration (gated on local Supabase): the queued -> running -> completed state
machine via ``run_analysis`` (which opens its OWN app-engine session), plus
cancel, the startup reaper, cache hits / force-rerun, in-flight serialization,
and the deep->standard downgrade. Pure ``compute_inputs_hash`` is tested without
a DB.

``run_analysis`` and the post-run reads use the process-wide app engine
(``get_sessionmaker``); an autouse fixture resets that lru_cache each test so
the engine binds to the test's own event loop (function-scoped by default).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest_asyncio
from app.db import get_sessionmaker
from app.models import AnalysisDepth, AnalysisStatus
from app.services.analyze import (
    cancel_analysis,
    compute_inputs_hash,
    create_queued_analysis,
    get_analysis,
    list_analyses,
    reap_orphaned_analyses,
    run_analysis,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import (
    LOCAL_DB_URL,
    insert_itinerary,
    insert_node,
    integration,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2024, 6, 20, h, m, tzinfo=UTC)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_app_engine() -> AsyncIterator[None]:
    """Bind the process-wide app engine to this test's event loop."""
    from app import db as _db

    _db.get_engine.cache_clear()
    _db.get_sessionmaker.cache_clear()
    try:
        yield
    finally:
        await _db.dispose_engine()


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _seed_trip(db_session: AsyncSession) -> uuid.UUID:
    iid = await insert_itinerary(db_session)
    await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Museum",
        starts_lower=_at(9),
        starts_upper=_at(10),
        lat=35.6812,
        lng=139.7671,
    )
    return iid


# ── pure ──────────────────────────────────────────────────────────────


def test_inputs_hash_is_order_independent_and_depth_sensitive() -> None:
    a = compute_inputs_hash(["n2", "n1"], ["e2", "e1"], {"branches": "all"}, "standard")
    b = compute_inputs_hash(["n1", "n2"], ["e1", "e2"], {"branches": "all"}, "standard")
    assert a == b  # node/edge ordering doesn't change the hash
    c = compute_inputs_hash(["n1", "n2"], ["e1", "e2"], {"branches": "all"}, "shallow")
    assert a != c  # depth does


# ── lifecycle ───────────────────────────────────────────────────────────


@integration
async def test_full_lifecycle_queued_to_completed(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    outcome = await create_queued_analysis(
        db_session, itinerary_id=iid, depth=AnalysisDepth.standard
    )
    assert outcome.scheduled is True
    assert outcome.analysis.status is AnalysisStatus.queued
    aid = outcome.analysis.id

    await run_analysis(aid)

    async with get_sessionmaker()() as s2:
        found = await get_analysis(s2, itinerary_id=iid, analysis_id=aid)
    assert found is not None
    analysis, _findings = found
    assert analysis.status is AnalysisStatus.completed
    assert analysis.result is not None
    assert analysis.summary
    assert analysis.started_at is not None
    assert analysis.completed_at is not None
    assert analysis.result["stats"]["node_count"] == 1


@integration
async def test_cancel_before_run_is_noop_run(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    outcome = await create_queued_analysis(
        db_session, itinerary_id=iid, depth=AnalysisDepth.shallow
    )
    aid = outcome.analysis.id

    cancelled = await cancel_analysis(db_session, itinerary_id=iid, analysis_id=aid)
    assert cancelled is not None
    assert cancelled.status is AnalysisStatus.cancelled

    await run_analysis(aid)  # must not resurrect a cancelled run

    async with get_sessionmaker()() as s2:
        found = await get_analysis(s2, itinerary_id=iid, analysis_id=aid)
    assert found is not None
    analysis, findings = found
    assert analysis.status is AnalysisStatus.cancelled
    assert findings == []


@integration
async def test_cancel_is_idempotent(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    outcome = await create_queued_analysis(db_session, itinerary_id=iid)
    aid = outcome.analysis.id
    await cancel_analysis(db_session, itinerary_id=iid, analysis_id=aid)
    again = await cancel_analysis(db_session, itinerary_id=iid, analysis_id=aid)
    assert again is not None and again.status is AnalysisStatus.cancelled


@integration
async def test_cancel_unknown_returns_none(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    res = await cancel_analysis(db_session, itinerary_id=iid, analysis_id=uuid.uuid4())
    assert res is None


@integration
async def test_cache_hit_and_force_rerun(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    o1 = await create_queued_analysis(db_session, itinerary_id=iid, depth=AnalysisDepth.standard)
    await run_analysis(o1.analysis.id)

    async with get_sessionmaker()() as s2:
        o2 = await create_queued_analysis(s2, itinerary_id=iid, depth=AnalysisDepth.standard)
        assert o2.cache_hit is True
        assert o2.scheduled is False
        assert o2.analysis.id == o1.analysis.id

        o3 = await create_queued_analysis(
            s2, itinerary_id=iid, depth=AnalysisDepth.standard, force_rerun=True
        )
        assert o3.scheduled is True
        assert o3.cache_hit is False
        assert o3.analysis.id != o1.analysis.id


@integration
async def test_in_flight_serialization(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    o1 = await create_queued_analysis(db_session, itinerary_id=iid)
    assert o1.scheduled is True
    # Second start while the first is still queued returns the existing row.
    async with get_sessionmaker()() as s2:
        o2 = await create_queued_analysis(s2, itinerary_id=iid)
    assert o2.in_flight is True
    assert o2.scheduled is False
    assert o2.analysis.id == o1.analysis.id


@integration
async def test_reaper_fails_stale_running(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    rid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            insert into public.analyses
              (id, itinerary_id, status, depth, started_at)
            values
              (:id, :iid, 'running', 'standard', now() - interval '1 hour')
            """
        ),
        {"id": rid, "iid": iid},
    )
    await db_session.commit()

    reaped = await reap_orphaned_analyses(db_session, max_running_seconds=600)
    assert reaped >= 1

    async with get_sessionmaker()() as s2:
        found = await get_analysis(s2, itinerary_id=iid, analysis_id=rid)
    assert found is not None
    analysis, _ = found
    assert analysis.status is AnalysisStatus.failed
    assert analysis.error_detail == "abandoned_at_restart"


@integration
async def test_fresh_running_is_not_reaped(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    rid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            insert into public.analyses
              (id, itinerary_id, status, depth, started_at)
            values (:id, :iid, 'running', 'standard', now())
            """
        ),
        {"id": rid, "iid": iid},
    )
    await db_session.commit()
    await reap_orphaned_analyses(db_session, max_running_seconds=600)
    async with get_sessionmaker()() as s2:
        found = await get_analysis(s2, itinerary_id=iid, analysis_id=rid)
    assert found is not None and found[0].status is AnalysisStatus.running


@integration
async def test_deep_downgrades_to_standard(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    outcome = await create_queued_analysis(db_session, itinerary_id=iid, depth=AnalysisDepth.deep)
    await run_analysis(outcome.analysis.id)
    async with get_sessionmaker()() as s2:
        found = await get_analysis(s2, itinerary_id=iid, analysis_id=outcome.analysis.id)
    assert found is not None
    analysis, findings = found
    assert analysis.status is AnalysisStatus.completed
    assert analysis.result is not None
    assert analysis.result.get("degraded_from") == "deep"
    assert any(f.category == "degraded" for f in findings)


@integration
async def test_list_analyses_most_recent_first(db_session: AsyncSession) -> None:
    iid = await _seed_trip(db_session)
    o1 = await create_queued_analysis(db_session, itinerary_id=iid)
    await run_analysis(o1.analysis.id)
    async with get_sessionmaker()() as s2:
        o2 = await create_queued_analysis(s2, itinerary_id=iid, force_rerun=True)
        rows = await list_analyses(s2, itinerary_id=iid, limit=20)
    ids = [r.id for r in rows]
    assert ids[0] == o2.analysis.id  # newest first
    assert o1.analysis.id in ids
