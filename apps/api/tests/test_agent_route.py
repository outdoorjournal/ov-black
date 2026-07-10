"""Tests for ``POST /agent/route`` — computeRoutes behind the agent token.

The Google call goes through the ``get_routes_client`` dependency override
(``MockTransport``), and the endpoint's ``get_settings`` is monkeypatched so
a key is present. Agent-token minting mirrors test_agent_internal_router.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from app.config import Settings
from app.main import app as fastapi_app
from app.routers import agent_internal as agent_internal_module
from app.routers.agent_internal import get_routes_client
from app.services import agent_token as agent_token_module
from app.services.agent_token import mint_agent_token
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

_SECRET = "test-agent-token-signing-secret-please-rotate"


def _settings() -> Settings:
    return Settings(
        agent_token_signing_secret=_SECRET,
        google_places_api_key="test-routes-key",
    )


@pytest.fixture()
def http_client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture(autouse=True)
def _patched_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings()
    monkeypatch.setattr(agent_token_module, "get_settings", lambda: s)
    monkeypatch.setattr(agent_internal_module, "get_settings", lambda: s)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    fastapi_app.dependency_overrides.pop(get_routes_client, None)


def _agent_headers() -> dict[str, str]:
    token = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=_settings(),
    )
    return {"Authorization": f"Bearer {token}"}


_COMPUTE_ROUTES_OK: dict[str, Any] = {
    "routes": [
        {
            "distanceMeters": 96432,
            "duration": "5411s",
            "polyline": {"encodedPolyline": "abc123encoded"},
            "legs": [
                {
                    "distanceMeters": 96432,
                    "duration": "5411s",
                    "startLocation": {"latLng": {"latitude": 35.68, "longitude": 139.76}},
                    "endLocation": {"latLng": {"latitude": 35.23, "longitude": 139.1}},
                }
            ],
        }
    ]
}


def _override_routes(handler: Any) -> None:
    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    fastapi_app.dependency_overrides[get_routes_client] = _factory


def test_route_computes_plan(http_client: TestClient) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["field_mask"] = request.headers.get("X-Goog-FieldMask", "")
        captured["key"] = request.headers.get("X-Goog-Api-Key", "")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=_COMPUTE_ROUTES_OK)

    _override_routes(handler)

    resp = http_client.post(
        "/agent/route",
        json={"origin": "Tokyo Station", "destination": "Hakone", "mode": "drive"},
        headers=_agent_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["origin"] == "Tokyo Station"
    assert body["destination"] == "Hakone"
    assert body["mode"] == "drive"
    assert body["distance_meters"] == 96432
    assert body["duration_seconds"] == 5411
    assert body["encoded_polyline"] == "abc123encoded"
    assert body["legs"][0]["start_lat"] == pytest.approx(35.68)
    assert body["legs"][0]["end_lng"] == pytest.approx(139.1)

    assert captured["key"] == "test-routes-key"
    assert "routes.polyline.encodedPolyline" in captured["field_mask"]
    assert '"travelMode": "DRIVE"' in captured["body"] or '"travelMode":"DRIVE"' in captured["body"]


def test_route_forwards_waypoints(http_client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"intermediates" in request.read()
        return httpx.Response(200, json=_COMPUTE_ROUTES_OK)

    _override_routes(handler)

    resp = http_client.post(
        "/agent/route",
        json={
            "origin": "Kyoto",
            "destination": "Kanazawa",
            "waypoints": ["Lake Biwa"],
        },
        headers=_agent_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["waypoints"] == ["Lake Biwa"]


def test_route_no_route_404s(http_client: TestClient) -> None:
    _override_routes(lambda request: httpx.Response(200, json={"routes": []}))

    resp = http_client.post(
        "/agent/route",
        json={"origin": "Honolulu", "destination": "Tokyo", "mode": "drive"},
        headers=_agent_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "route_not_found"


def test_route_upstream_failure_502s(http_client: TestClient) -> None:
    _override_routes(lambda request: httpx.Response(500, json={}))

    resp = http_client.post(
        "/agent/route",
        json={"origin": "A", "destination": "B"},
        headers=_agent_headers(),
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "route_upstream_error"


def test_route_rejects_supabase_jwt_and_anonymous(http_client: TestClient) -> None:
    resp = http_client.post("/agent/route", json={"origin": "A", "destination": "B"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "agent_unauthorized"


def test_route_invalid_mode_422s(http_client: TestClient) -> None:
    resp = http_client.post(
        "/agent/route",
        json={"origin": "A", "destination": "B", "mode": "teleport"},
        headers=_agent_headers(),
    )
    assert resp.status_code == 422
