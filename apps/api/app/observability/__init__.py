"""Observability primitives (M005 / obs).

Lightweight, dependency-free, OTel-ready:

- structured logging with a request-correlated context (:mod:`logging`,
  :mod:`context`);
- per-request access log + latency metrics + correlation header
  (:class:`RequestContextMiddleware`);
- CloudWatch EMF metrics with no extra infra (:func:`emit_metric`);
- log-based spans behind a swappable recorder seam (:func:`span` /
  :func:`set_span_recorder`);
- slow-query DB instrumentation (:func:`instrument_engine`);
- a global 500 handler that surfaces the ``request_id``
  (:func:`install_exception_handlers`).

Swapping in OpenTelemetry later means re-pointing :func:`emit_metric` and
:func:`set_span_recorder` — call sites do not change.
"""

from __future__ import annotations

from app.observability.context import (
    bind_context,
    get_context,
    get_request_id,
    new_request_id,
    reset_context,
)
from app.observability.db import instrument_engine
from app.observability.errors import install_exception_handlers
from app.observability.logging import configure_logging, safe_extra
from app.observability.metrics import emit_metric
from app.observability.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.observability.tracing import set_span_recorder, span, span_sync

__all__ = [
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "bind_context",
    "configure_logging",
    "emit_metric",
    "get_context",
    "get_request_id",
    "install_exception_handlers",
    "instrument_engine",
    "new_request_id",
    "reset_context",
    "safe_extra",
    "set_span_recorder",
    "span",
    "span_sync",
]
