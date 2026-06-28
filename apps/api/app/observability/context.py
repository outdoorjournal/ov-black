"""Request-scoped logging context (M005 / obs).

A single :class:`contextvars.ContextVar` holds an immutable dict of fields that
the log formatter merges into every line emitted during a request — most
importantly ``request_id``, so a whole request's logs (and any downstream span /
metric) share one correlation id. ContextVars copy into child tasks, so a
``BackgroundTask`` or an ``anyio.to_thread`` offload spawned inside a request
keeps the same context.

Nothing here ever logs sensitive data — callers decide what to ``bind``. Keep
Dossier / OSINT / net-worth / card / token material OUT of the context dict (the
redaction sweeps assert no sentinel leaks into any record).
"""

from __future__ import annotations

import contextvars
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# Immutable-by-convention: every mutation replaces the dict via ``.set`` rather
# than mutating in place. Default is ``None`` (B039 — no mutable default) and
# read back as an empty dict.
_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ovb_log_context",
    default=None,
)


def new_request_id() -> str:
    """A fresh correlation id (hex uuid4)."""
    return uuid.uuid4().hex


def get_context() -> dict[str, Any]:
    """The fields bound for the current request/task (possibly empty)."""
    return _LOG_CONTEXT.get() or {}


def get_request_id() -> str | None:
    """The current request's correlation id, if one is bound."""
    rid = (_LOG_CONTEXT.get() or {}).get("request_id")
    return rid if isinstance(rid, str) else None


def bind_context(**fields: Any) -> contextvars.Token[dict[str, Any] | None]:
    """Merge ``fields`` (dropping ``None`` values) into the current context.

    Returns a token to pass to :func:`reset_context` — bind/reset must be paired
    so context never leaks past the request that set it.
    """
    current = _LOG_CONTEXT.get() or {}
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    return _LOG_CONTEXT.set(merged)


def bind(fields: Mapping[str, Any]) -> contextvars.Token[dict[str, Any] | None]:
    """Mapping form of :func:`bind_context` for dynamic field sets."""
    return bind_context(**dict(fields))


def reset_context(token: contextvars.Token[dict[str, Any] | None]) -> None:
    """Restore the context to the state captured by ``token``."""
    _LOG_CONTEXT.reset(token)
