"""Observability primitives — logging context, formatters, metrics, middleware.

Pure unit tests (no DB / no network): they construct the formatters and a tiny
FastAPI app directly so the request-id correlation, the access log, the EMF
metric envelope, and the global 500 handler are all exercisable offline.
"""

from __future__ import annotations

import json
import logging

import pytest
from app.observability import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    bind_context,
    emit_metric,
    get_context,
    get_request_id,
    install_exception_handlers,
    reset_context,
    span_sync,
)
from app.observability.logging import ConsoleFormatter, JsonFormatter, safe_extra
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── context ────────────────────────────────────────────────────────────────


def test_bind_and_reset_context_roundtrip() -> None:
    assert get_request_id() is None
    token = bind_context(request_id="abc123", method="GET")
    try:
        assert get_request_id() == "abc123"
        assert get_context()["method"] == "GET"
        # None values are dropped, existing keys preserved on re-bind.
        inner = bind_context(route="/x", method=None)
        assert get_context()["route"] == "/x"
        assert get_context()["method"] == "GET"
        reset_context(inner)
    finally:
        reset_context(token)
    assert get_request_id() is None
    assert get_context() == {}


# ── formatters ─────────────────────────────────────────────────────────────


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("ov_black.test", logging.INFO, __file__, 1, msg, None, None)
    record.__dict__.update(extra)
    return record


def test_json_formatter_emits_event_and_extras() -> None:
    fmt = JsonFormatter(service_name="ov-black-api", env="staging")
    line = fmt.format(_record("invoice.payment", invoice_id="i-1", status="succeeded"))
    obj = json.loads(line)
    assert obj["event"] == "invoice.payment"
    assert obj["level"] == "INFO"
    assert obj["service"] == "ov-black-api"
    assert obj["env"] == "staging"
    assert obj["invoice_id"] == "i-1"
    assert obj["status"] == "succeeded"


def test_json_formatter_merges_bound_context() -> None:
    fmt = JsonFormatter(service_name="svc", env="local")
    token = bind_context(request_id="rid-9", route="/invoices/{id}/pay")
    try:
        obj = json.loads(fmt.format(_record("http.request")))
    finally:
        reset_context(token)
    assert obj["request_id"] == "rid-9"
    assert obj["route"] == "/invoices/{id}/pay"


def test_console_formatter_is_readable_and_hides_secrets_caller_supplies() -> None:
    fmt = ConsoleFormatter()
    out = fmt.format(_record("db.slow_query", duration_ms=812.5))
    assert "db.slow_query" in out
    assert "duration_ms=812.5" in out


def test_safe_extra_renames_reserved_keys() -> None:
    # ``name``/``module`` collide with LogRecord attrs and would raise if passed
    # straight through as ``extra``.
    out = safe_extra({"name": "duffel", "module": "x", "source": "ov"})
    assert out == {"x_name": "duffel", "x_module": "x", "source": "ov"}


# ── metrics ────────────────────────────────────────────────────────────────


def test_emit_metric_writes_emf_envelope(caplog: pytest.LogCaptureFixture) -> None:
    # The metrics logger has propagate disabled only after configure_logging; in
    # a bare unit test it propagates, so caplog sees the raw EMF line.
    metrics_logger = logging.getLogger("ov_black.metrics")
    metrics_logger.propagate = True
    with caplog.at_level(logging.INFO, logger="ov_black.metrics"):
        emit_metric("http.request.latency", 12.5, unit="Milliseconds", dimensions={"Route": "/x"})
    line = next(r.getMessage() for r in caplog.records if r.name == "ov_black.metrics")
    obj = json.loads(line)
    assert obj["http.request.latency"] == 12.5
    assert obj["Route"] == "/x"
    assert obj["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "Milliseconds"
    assert "Service" in obj and "Env" in obj


def test_emit_metric_muted_when_disabled(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import Settings
    from app.observability import metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "get_settings", lambda: Settings(metrics_enabled=False))
    logging.getLogger("ov_black.metrics").propagate = True
    with caplog.at_level(logging.INFO, logger="ov_black.metrics"):
        emit_metric("payment.count", 1)
    assert not [r for r in caplog.records if r.name == "ov_black.metrics"]


# ── spans ──────────────────────────────────────────────────────────────────


def test_span_sync_logs_a_span(caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level(logging.INFO, logger="ov_black.span"),
        span_sync("payment.gateway.sale", gateway="fake"),
    ):
        pass
    rec = next(r for r in caplog.records if r.name == "ov_black.span")
    assert rec.getMessage() == "span"
    assert rec.span == "payment.gateway.sale"
    assert rec.gateway == "fake"
    assert isinstance(rec.duration_ms, float)


# ── middleware + global 500 handler ──────────────────────────────────────────


@pytest.fixture()
def obs_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, log_requests=True, metrics=False)
    install_exception_handlers(app)

    @app.get("/ok")
    async def _ok() -> dict[str, str]:
        return {"request_id": get_request_id() or ""}

    @app.get("/boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    return TestClient(app, raise_server_exceptions=False)


def test_request_gets_correlation_header(obs_client: TestClient) -> None:
    resp = obs_client.get("/ok")
    assert resp.status_code == 200
    rid = resp.headers.get(REQUEST_ID_HEADER)
    assert rid
    # The same id the handler observed via the contextvar is echoed on the header.
    assert resp.json()["request_id"] == rid


def test_inbound_request_id_is_honored(obs_client: TestClient) -> None:
    resp = obs_client.get("/ok", headers={REQUEST_ID_HEADER: "caller-supplied-id"})
    assert resp.headers.get(REQUEST_ID_HEADER) == "caller-supplied-id"
    assert resp.json()["request_id"] == "caller-supplied-id"


def test_unhandled_exception_becomes_500_with_request_id(
    obs_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="ov_black.request"):
        resp = obs_client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "internal_error"
    assert body["request_id"]
    assert body["request_id"] == resp.headers.get(REQUEST_ID_HEADER)
    # The traceback was logged with the bound context (not swallowed).
    err = next(r for r in caplog.records if r.getMessage() == "http.request.error")
    assert err.exc_info is not None
