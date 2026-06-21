"""Async Analyze service (TravelGraph Phase 5 / B5).

Public surface:

- :func:`create_queued_analysis` — POST entrypoint. Returns an existing
  in-flight run, a recent cache hit, or a freshly-queued row to schedule.
- :func:`run_analysis` — the ``BackgroundTasks`` entrypoint. Opens its OWN
  session (the request session is closed by the time it runs), drives the
  ``queued -> running -> completed | failed | cancelled`` state machine, and
  swallows its own exceptions (FastAPI discards BackgroundTask errors).
- :func:`cancel_analysis`, :func:`get_analysis`, :func:`list_analyses`.
- :func:`reap_orphaned_analyses` — startup sweep for runners abandoned by a
  crash/restart.

Analyze is read-only over the graph. Depth is chosen by the caller, never
inferred (D-ANALYZE); ``deep`` is downgraded to ``standard`` for the MVP and
the downgrade is recorded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import (
    Analysis,
    AnalysisDepth,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
)
from app.services.analyze_runners import shallow, standard
from app.services.analyze_runners.common import (
    Finding,
    RunOutput,
    build_result,
    load_edges,
    load_timeline_nodes,
)

logger = logging.getLogger("ov_black.api")

# Runner per depth. `deep` reuses the standard runner for the MVP (live data
# deferred) — the downgrade is recorded on the result (see _dispatch).
_RUNNERS = {
    AnalysisDepth.shallow: shallow.run,
    AnalysisDepth.standard: standard.run,
    AnalysisDepth.deep: standard.run,
}

# Cache TTL per depth — a re-request matching (itinerary, inputs_hash, depth)
# within the window returns the prior completed run instead of recomputing.
_CACHE_TTL: dict[AnalysisDepth, timedelta] = {
    AnalysisDepth.shallow: timedelta(minutes=5),
    AnalysisDepth.standard: timedelta(minutes=60),
    AnalysisDepth.deep: timedelta(hours=24),
}

_TERMINAL = {
    AnalysisStatus.completed,
    AnalysisStatus.failed,
    AnalysisStatus.cancelled,
}


@dataclass(frozen=True, slots=True)
class StartOutcome:
    """Result of :func:`create_queued_analysis`.

    ``scheduled`` is True only for a brand-new ``queued`` row the caller must
    hand to ``BackgroundTasks``. ``in_flight``/``cache_hit`` return an existing
    row and must NOT be re-scheduled.
    """

    analysis: Analysis
    scheduled: bool
    cache_hit: bool = False
    in_flight: bool = False


# ── inputs hash ───────────────────────────────────────────────────────


def compute_inputs_hash(
    node_ids: list[str],
    edge_ids: list[str],
    scope: dict[str, Any],
    depth: str,
) -> str:
    """sha256 of the canonicalized graph state + scope + depth (handoff §6).

    Catches a re-run on the same graph state; intentionally does NOT catch a
    node's ``metadata`` edit that leaves ids unchanged (force_rerun bypasses).
    """
    canonical = {
        "nodes": sorted(node_ids),
        "edges": sorted(edge_ids),
        "scope": scope,
        "depth": depth,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _load_hash_inputs(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    scope: dict[str, Any],
) -> tuple[list[str], list[str]]:
    nodes = await load_timeline_nodes(session, itinerary_id=itinerary_id, scope=scope)
    edges = await load_edges(session, itinerary_id=itinerary_id)
    return [str(n.node_id) for n in nodes], [str(e[0]) for e in edges]


# ── create / queue ────────────────────────────────────────────────────


async def create_queued_analysis(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    depth: AnalysisDepth = AnalysisDepth.standard,
    scope: dict[str, Any] | None = None,
    requested_by: uuid.UUID | None = None,
    requested_kind: str = "user",
    force_rerun: bool = False,
) -> StartOutcome:
    """Return an in-flight run, a recent cache hit, or a new queued row.

    Per-itinerary serialization: at most one ``queued``/``running`` row exists
    at a time, so a second start while one is in flight returns the existing
    row (handoff §3.4) rather than racing a second runner over the same graph.
    """
    scope = scope or {}

    in_flight = (
        await session.execute(
            select(Analysis)
            .where(
                Analysis.itinerary_id == itinerary_id,
                Analysis.status.in_([AnalysisStatus.queued, AnalysisStatus.running]),
            )
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if in_flight is not None:
        return StartOutcome(analysis=in_flight, scheduled=False, in_flight=True)

    node_ids, edge_ids = await _load_hash_inputs(session, itinerary_id=itinerary_id, scope=scope)
    inputs_hash = compute_inputs_hash(node_ids, edge_ids, scope, depth.value)

    if not force_rerun:
        ttl = _CACHE_TTL[depth]
        cached_id = (
            await session.execute(
                text(
                    """
                    select id from public.analyses
                    where itinerary_id = :iid
                      and inputs_hash = :h
                      and depth = cast(:d as public.analysis_depth)
                      and status = 'completed'
                      and completed_at >= now() - make_interval(secs => :ttl)
                    order by completed_at desc
                    limit 1
                    """
                ),
                {
                    "iid": itinerary_id,
                    "h": inputs_hash,
                    "d": depth.value,
                    "ttl": int(ttl.total_seconds()),
                },
            )
        ).scalar_one_or_none()
        if cached_id is not None:
            cached = (
                await session.execute(select(Analysis).where(Analysis.id == cached_id))
            ).scalar_one()
            return StartOutcome(analysis=cached, scheduled=False, cache_hit=True)

    analysis = Analysis(
        itinerary_id=itinerary_id,
        status=AnalysisStatus.queued,
        depth=depth,
        scope=scope,
        inputs_hash=inputs_hash,
        requested_by=requested_by,
        requested_kind=requested_kind,
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return StartOutcome(analysis=analysis, scheduled=True)


# ── background runner ─────────────────────────────────────────────────


async def run_analysis(analysis_id: uuid.UUID) -> None:
    """``BackgroundTasks`` entrypoint — opens its own session.

    Wraps every transition; on an uncaught exception flips the row to
    ``failed`` and NEVER re-raises (FastAPI would discard it into the void).
    """
    async with get_sessionmaker()() as session:
        try:
            analysis = await _begin_running(session, analysis_id)
            if analysis is None:
                return  # cancelled before start, or already gone
            output = await _dispatch(session, analysis)
            await _complete(session, analysis_id, analysis.depth, output)
        except asyncio.CancelledError:
            await _mark_cancelled(session, analysis_id, "task_cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 — must not leak out of the task
            logger.exception("analyze.run.failed", extra={"analysis_id": str(analysis_id)})
            await _mark_failed(session, analysis_id, str(exc)[:1000])


async def _begin_running(session: AsyncSession, analysis_id: uuid.UUID) -> Analysis | None:
    """Transition ``queued -> running``. Returns None if no longer queued."""
    analysis = (
        await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    ).scalar_one_or_none()
    if analysis is None or analysis.status is not AnalysisStatus.queued:
        return None
    analysis.status = AnalysisStatus.running
    analysis.started_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(analysis)
    return analysis


async def _dispatch(session: AsyncSession, analysis: Analysis) -> RunOutput:
    """Run the depth's runner; downgrade ``deep`` to ``standard`` + record it."""
    runner = _RUNNERS[analysis.depth]
    output = await runner(
        session,
        itinerary_id=analysis.itinerary_id,
        scope=analysis.scope or {},
    )
    if analysis.depth is AnalysisDepth.deep:
        note = Finding(
            severity=FindingSeverity.info,
            category="degraded",
            message="Deep (live-data) analysis isn't available yet — ran standard.",
            node_id=None,
            evidence={"requested_depth": "deep", "ran_depth": "standard"},
        )
        return RunOutput(
            findings=[note, *output.findings],
            node_count=output.node_count,
            fuzz_count=output.fuzz_count,
            result_extra={**output.result_extra, "degraded_from": "deep"},
            external_calls=output.external_calls,
        )
    return output


async def _complete(
    session: AsyncSession,
    analysis_id: uuid.UUID,
    depth: AnalysisDepth,
    output: RunOutput,
) -> None:
    """Write findings + aggregate result, flip ``running -> completed``.

    Re-checks status first: if a cancel landed mid-run, the cancel wins and
    nothing is overwritten (terminal states are immutable).
    """
    analysis = (
        await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    ).scalar_one_or_none()
    if analysis is None or analysis.status is not AnalysisStatus.running:
        return
    result = build_result(output, depth=depth.value)
    session.add_all(
        [
            AnalysisFinding(
                analysis_id=analysis_id,
                node_id=f.node_id,
                severity=f.severity,
                category=f.category,
                message=f.message,
                evidence=f.evidence,
                suggested_fix=f.suggested_fix,
            )
            for f in output.findings
        ]
    )
    analysis.status = AnalysisStatus.completed
    analysis.completed_at = datetime.now(UTC)
    analysis.result = result
    analysis.summary = result["summary"]
    analysis.external_calls = output.external_calls
    await session.commit()


async def _mark_failed(session: AsyncSession, analysis_id: uuid.UUID, detail: str) -> None:
    await session.rollback()
    analysis = (
        await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    ).scalar_one_or_none()
    if analysis is None or analysis.status in _TERMINAL:
        return
    analysis.status = AnalysisStatus.failed
    analysis.completed_at = datetime.now(UTC)
    analysis.error_detail = detail
    await session.commit()


async def _mark_cancelled(session: AsyncSession, analysis_id: uuid.UUID, detail: str) -> None:
    await session.rollback()
    analysis = (
        await session.execute(select(Analysis).where(Analysis.id == analysis_id))
    ).scalar_one_or_none()
    if analysis is None or analysis.status in _TERMINAL:
        return
    analysis.status = AnalysisStatus.cancelled
    analysis.completed_at = datetime.now(UTC)
    analysis.error_detail = detail
    await session.commit()


# ── read / cancel ─────────────────────────────────────────────────────


async def cancel_analysis(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> Analysis | None:
    """Cancel a not-yet-terminal run. Idempotent; returns None if not found.

    Scoped to ``itinerary_id`` so a caller can't cancel another itinerary's run.
    """
    analysis = (
        await session.execute(
            select(Analysis).where(
                Analysis.id == analysis_id,
                Analysis.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        return None
    if analysis.status not in _TERMINAL:
        analysis.status = AnalysisStatus.cancelled
        analysis.completed_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(analysis)
    return analysis


async def get_analysis(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    analysis_id: uuid.UUID,
) -> tuple[Analysis, list[AnalysisFinding]] | None:
    """Return ``(analysis, findings)`` or None if not found in this itinerary."""
    analysis = (
        await session.execute(
            select(Analysis).where(
                Analysis.id == analysis_id,
                Analysis.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        return None
    findings = list(
        (
            await session.execute(
                select(AnalysisFinding)
                .where(AnalysisFinding.analysis_id == analysis_id)
                .order_by(AnalysisFinding.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return analysis, findings


async def list_analyses(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    limit: int = 20,
) -> list[Analysis]:
    """Most-recent-first list of runs for an itinerary (no findings)."""
    return list(
        (
            await session.execute(
                select(Analysis)
                .where(Analysis.itinerary_id == itinerary_id)
                .order_by(Analysis.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


# ── startup reaper ────────────────────────────────────────────────────


async def reap_orphaned_analyses(
    session: AsyncSession,
    *,
    max_running_seconds: int = 600,
) -> int:
    """Fail any ``running`` row older than the threshold (handoff §3.5).

    Called once at startup: a runner abandoned by a crash/restart leaves a
    ``running`` row no live task will ever complete. Returns the count reaped.
    """
    result = await session.execute(
        text(
            """
            update public.analyses
               set status = 'failed',
                   error_detail = 'abandoned_at_restart',
                   completed_at = now(),
                   updated_at = now()
             where status = 'running'
               and started_at < now() - make_interval(secs => :max_secs)
            """
        ),
        {"max_secs": max_running_seconds},
    )
    await session.commit()
    return cast("CursorResult[Any]", result).rowcount or 0
