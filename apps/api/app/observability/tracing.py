"""Lightweight spans — log-based now, OTel-ready by seam (M005 / obs).

A :func:`span` (async) / :func:`span_sync` (sync) context manager times a block
and hands ``(name, duration_ms, ok, attributes)`` to a pluggable *recorder*. The
default recorder logs a ``span`` line (carrying the bound ``request_id``) and,
when ``metric=True``, emits EMF duration + count metrics.

To graduate to real OpenTelemetry later, call :func:`set_span_recorder` with a
recorder that starts/ends an OTel span instead — every ``async with span(...)``
call site stays exactly as written. That is the whole point of routing through a
single seam rather than sprinkling ``logger.info`` + timers by hand.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, Protocol

from app.observability.logging import safe_extra
from app.observability.metrics import emit_metric

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping

_logger = logging.getLogger("ov_black.span")


class SpanRecorder(Protocol):
    """Seam an OTel adapter implements to replace the default log recorder."""

    def __call__(
        self,
        *,
        name: str,
        duration_ms: float,
        ok: bool,
        attributes: Mapping[str, Any],
        metric: bool,
    ) -> None: ...


def _log_recorder(
    *,
    name: str,
    duration_ms: float,
    ok: bool,
    attributes: Mapping[str, Any],
    metric: bool,
) -> None:
    level = logging.INFO if ok else logging.WARNING
    _logger.log(
        level,
        "span",
        extra=safe_extra(
            {"span": name, "duration_ms": round(duration_ms, 2), "ok": ok, **attributes}
        ),
    )
    if metric:
        emit_metric(
            "span.duration",
            duration_ms,
            unit="Milliseconds",
            dimensions={"Span": name},
            ok=ok,
        )
        emit_metric(
            "span.count",
            1,
            dimensions={"Span": name, "Ok": str(ok).lower()},
        )


_recorder: SpanRecorder = _log_recorder


def set_span_recorder(recorder: SpanRecorder) -> None:
    """Swap the span recorder (e.g. install an OpenTelemetry-backed one)."""
    global _recorder
    _recorder = recorder


@asynccontextmanager
async def span(name: str, *, metric: bool = False, **attributes: Any) -> AsyncIterator[None]:
    """Time an async block as a span. ``metric=True`` also emits EMF metrics."""
    start = time.perf_counter()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        _recorder(
            name=name,
            duration_ms=(time.perf_counter() - start) * 1000,
            ok=ok,
            attributes=attributes,
            metric=metric,
        )


@contextmanager
def span_sync(name: str, *, metric: bool = False, **attributes: Any) -> Iterator[None]:
    """Synchronous counterpart to :func:`span`."""
    start = time.perf_counter()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        _recorder(
            name=name,
            duration_ms=(time.perf_counter() - start) * 1000,
            ok=ok,
            attributes=attributes,
            metric=metric,
        )
