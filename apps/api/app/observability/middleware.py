"""Request-context + access-log middleware (M005 / obs).

Wraps every request to:

1. mint (or honor an inbound ``X-Request-Id``) correlation id and bind it — plus
   method/route — to the logging context so *every* log line for the request is
   correlated, and echo it back on the response header;
2. time the request and emit one ``http.request`` access line + EMF
   latency/count metrics keyed by the matched **route template** (not the raw
   path, to keep metric cardinality bounded);
3. log any unhandled exception with a full traceback *while the context is still
   bound* (the response body is produced by the global 500 handler).

It sits just inside CORS and outside the JWT middleware, so even auth rejections
get a request id, an access line, and the echoed header.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.context import bind_context, new_request_id, reset_context
from app.observability.logging import safe_extra
from app.observability.metrics import emit_metric

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger("ov_black.request")

REQUEST_ID_HEADER = "x-request-id"

# Collapse high-cardinality path segments (uuids, long hex, pure digits) so a
# raw path can stand in as a bounded route label when no template matched.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX_RE = re.compile(r"^[0-9a-f]{16,}$", re.I)


def _collapse(path: str) -> str:
    parts = []
    for seg in path.split("/"):
        if seg.isdigit() or _UUID_RE.match(seg) or _HEX_RE.match(seg):
            parts.append(":id")
        else:
            parts.append(seg)
    return "/".join(parts) or "/"


def _route_label(request: Request) -> str:
    """The matched route template (low cardinality), or a collapsed path."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return _collapse(request.url.path)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlation id + access log + per-request latency metrics."""

    def __init__(
        self,
        app: Any,
        *,
        log_requests: bool = True,
        metrics: bool = True,
    ) -> None:
        super().__init__(app)
        self._log = log_requests
        self._metrics = metrics

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = inbound if inbound and len(inbound) <= 128 else new_request_id()
        request.state.request_id = request_id

        token = bind_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                # Log here, with context still bound + full traceback. The
                # response is rendered by the global 500 handler (outer layer).
                logger.exception(
                    "http.request.error",
                    extra=safe_extra(
                        {
                            "status": 500,
                            "duration_ms": round(duration_ms, 2),
                            "route": _route_label(request),
                        }
                    ),
                )
                if self._metrics:
                    self._emit(request, status=500, duration_ms=duration_ms)
                raise

            duration_ms = (time.perf_counter() - start) * 1000
            route = _route_label(request)
            status = response.status_code
            if self._log:
                logger.log(
                    logging.WARNING if status >= 500 else logging.INFO,
                    "http.request",
                    extra=safe_extra(
                        {"status": status, "duration_ms": round(duration_ms, 2), "route": route}
                    ),
                )
            if self._metrics:
                self._emit(request, status=status, duration_ms=duration_ms, route=route)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            reset_context(token)

    def _emit(
        self,
        request: Request,
        *,
        status: int,
        duration_ms: float,
        route: str | None = None,
    ) -> None:
        dims = {"Route": route or _route_label(request), "Method": request.method}
        emit_metric("http.request.latency", duration_ms, unit="Milliseconds", dimensions=dims)
        emit_metric(
            "http.request.count",
            1,
            dimensions={**dims, "Status": str(status)},
        )
