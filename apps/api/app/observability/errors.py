"""Global exception handler (M005 / obs).

Turns an otherwise-bare unhandled exception into a clean JSON 500 that carries
the ``request_id`` — so a user (or the CLI/web client) can hand you the id and
you can pull the full traceback line straight out of CloudWatch. The traceback
itself is logged by :class:`RequestContextMiddleware` (where the context is
still bound), so this handler only shapes the response and never double-logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from app.observability.middleware import REQUEST_ID_HEADER

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {REQUEST_ID_HEADER: request_id} if isinstance(request_id, str) else None
    return JSONResponse(
        status_code=500,
        content={"detail": "internal_error", "request_id": request_id},
        headers=headers,
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unhandled_exception_handler)
