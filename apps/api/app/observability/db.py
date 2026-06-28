"""Database query instrumentation (M005 / obs).

Attaches SQLAlchemy ``before/after_cursor_execute`` listeners to the engine to
time every statement and warn (+ EMF metric) on anything slower than
``db_slow_query_ms``. This is the cheapest path-to-N+1/slow-query visibility:
when a request feels slow, the ``db.slow_query`` lines tell you which statement
and how long, correlated by ``request_id``.

Redaction: only the (already parameterized) statement *text* is logged, never
the bound ``parameters`` — values stay out of logs.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import event

from app.config import get_settings
from app.observability.metrics import emit_metric

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("ov_black.db")

_WS_RE = re.compile(r"\s+")
# Identity of sync engines already instrumented — guard against double-attach
# (the engine is an lru_cache singleton, but tests / re-wiring may call twice).
_INSTRUMENTED: set[int] = set()


def _summarize(statement: str, *, limit: int = 160) -> str:
    collapsed = _WS_RE.sub(" ", statement).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _op(statement: str) -> str:
    head = statement.lstrip().split(" ", 1)
    return head[0].upper() if head and head[0] else "OTHER"


def instrument_engine(async_engine: AsyncEngine) -> None:
    """Idempotently attach slow-query timing listeners to ``async_engine``."""
    sync_engine = async_engine.sync_engine
    if id(sync_engine) in _INSTRUMENTED:
        return
    _INSTRUMENTED.add(id(sync_engine))

    threshold_ms = get_settings().db_slow_query_ms

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        conn.info.setdefault("_ovb_query_stack", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        stack = conn.info.get("_ovb_query_stack")
        if not stack:
            return
        duration_ms = (time.perf_counter() - stack.pop()) * 1000
        if duration_ms < threshold_ms:
            return
        logger.warning(
            "db.slow_query",
            extra={
                "duration_ms": round(duration_ms, 2),
                "statement": _summarize(statement),
                "executemany": bool(executemany),
            },
        )
        emit_metric("db.slow_query", 1, dimensions={"Op": _op(statement)})
