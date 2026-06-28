"""Structured logging configuration (M005 / obs).

The whole codebase already logs in the ``logger.info("event.name", extra={...})``
shape, so a JSON formatter turns those into queryable CloudWatch Logs Insights
records for free — every line carries the ``event`` name, the bound
``request_id``, and any ``extra`` fields as top-level keys.

:func:`configure_logging` is **additive and idempotent**: it never clears the
root handler list (pytest's ``caplog`` attaches there), it just installs/updates
a single tagged handler. Format is ``text`` for local dev (readable console
lines) and ``json`` in staging/prod, or forced via ``LOG_FORMAT``.

EMF metric lines are emitted on a separate ``ov_black.metrics`` logger with a
raw passthrough formatter (``propagate=False``) so the ``_aws`` envelope reaches
CloudWatch verbatim instead of being wrapped by the JSON formatter.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from app.observability.context import get_context

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.config import Settings

# LogRecord attributes that are framework-owned — everything else on a record's
# ``__dict__`` is a user-supplied ``extra`` we want to surface.
_RESERVED: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)

_METRICS_LOGGER_NAME = "ov_black.metrics"
_HANDLER_TAG = "_ovb_handler"


def safe_extra(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Rename keys that collide with reserved LogRecord attributes.

    ``logging`` raises if an ``extra`` key shadows e.g. ``name`` or ``module``;
    span/metric attributes are arbitrary, so we prefix collisions with ``x_``.
    """
    out: dict[str, Any] = {}
    for key, value in fields.items():
        out[f"x_{key}" if key in _RESERVED else key] = value
    return out


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, event, context, extras."""

    def __init__(self, *, service_name: str, env: str) -> None:
        super().__init__()
        self._service = service_name
        self._env = env

    def format(self, record: logging.LogRecord) -> str:
        ts = _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "service": self._service,
            "env": self._env,
        }
        # Context (request_id, route, …) first, then per-call extras win.
        payload.update(get_context())
        payload.update(_record_extras(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line console format for local dev.

    ``HH:MM:SS LEVEL  logger  event  key=val …  [rid]`` plus an indented
    traceback when ``exc_info`` is present.
    """

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_context()
        fields = {**ctx, **_record_extras(record)}
        rid = fields.pop("request_id", None)
        ts = _dt.datetime.fromtimestamp(record.created, tz=_dt.UTC).strftime("%H:%M:%S")
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"{ts} {record.levelname:<7} {record.name}  {record.getMessage()}"
        if kv:
            line = f"{line}  {kv}"
        if rid:
            line = f"{line}  [{str(rid)[:8]}]"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def _find_tagged_handler(logger: logging.Logger) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_TAG, False):
            return handler
    return None


def configure_logging(settings: Settings) -> None:
    """Install the structured formatter on root + align uvicorn loggers.

    Idempotent: re-installs the formatter on our tagged handler rather than
    stacking handlers, and leaves any foreign handler (pytest caplog, etc.) in
    place.
    """
    resolved = settings.log_format
    if resolved == "auto":
        resolved = "text" if settings.env == "local" else "json"

    formatter: logging.Formatter
    if resolved == "json":
        formatter = JsonFormatter(service_name=settings.service_name, env=settings.env)
    else:
        formatter = ConsoleFormatter()

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    handler = _find_tagged_handler(root)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    handler.setFormatter(formatter)
    handler.setLevel(settings.log_level)

    # uvicorn ships its own handlers/formatters; route its loggers through ours
    # so server logs match app logs. uvicorn.access is muted — our request
    # middleware emits a richer access line keyed by route + request_id.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False

    _configure_metrics_logger()


def _configure_metrics_logger() -> None:
    """A dedicated logger that emits raw EMF lines (no JSON wrapping)."""
    lg = logging.getLogger(_METRICS_LOGGER_NAME)
    lg.setLevel(logging.INFO)
    lg.propagate = False  # keep EMF out of the app log stream + caplog
    handler = _find_tagged_handler(lg)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _HANDLER_TAG, True)
        lg.addHandler(handler)
    handler.setFormatter(logging.Formatter("%(message)s"))
