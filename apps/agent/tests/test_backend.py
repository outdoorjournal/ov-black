"""Backend HTTP client — JWT injection, error taxonomy."""

from __future__ import annotations

import httpx
import pytest

from agent.backend import BackendError, _auth_headers, _unwrap, jwt_ctx, pin_ctx


def test_auth_headers_requires_jwt() -> None:
    token = jwt_ctx.set(None)
    try:
        with pytest.raises(BackendError) as excinfo:
            _auth_headers()
        assert excinfo.value.reason == "missing_auth"
    finally:
        jwt_ctx.reset(token)


def test_auth_headers_when_set_returns_bearer() -> None:
    token = jwt_ctx.set("eyJfake")
    try:
        assert _auth_headers() == {"Authorization": "Bearer eyJfake"}
    finally:
        jwt_ctx.reset(token)


def test_unwrap_returns_json_on_2xx() -> None:
    response = httpx.Response(200, json={"hello": "world"})
    assert _unwrap(response) == {"hello": "world"}


def test_unwrap_none_on_empty_2xx() -> None:
    response = httpx.Response(204, content=b"")
    assert _unwrap(response) is None


def test_unwrap_raises_backend_error_with_detail() -> None:
    response = httpx.Response(409, json={"detail": "locked"})
    with pytest.raises(BackendError) as excinfo:
        _unwrap(response)
    assert excinfo.value.status == 409
    assert excinfo.value.reason == "locked"


def test_unwrap_raises_without_detail_falls_back_to_status() -> None:
    response = httpx.Response(500, text="boom")
    with pytest.raises(BackendError) as excinfo:
        _unwrap(response)
    assert excinfo.value.status == 500
    assert excinfo.value.reason == "http_500"


def test_pin_ctx_default_shape() -> None:
    assert pin_ctx.get() == {
        "client_id": None,
        "itinerary_id": None,
        "actor_kind": "user",
        "audience": "traveler",
    }
