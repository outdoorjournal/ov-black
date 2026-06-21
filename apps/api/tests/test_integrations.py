"""Tests for the third-party integration surfaces (Phase 4).

Weather + flight-status are still canned stubs; Google Places is now live
(B1) and proxied through ``GooglePlacesProvider``. The Places tests inject a
``MockTransport``-backed provider via the ``get_google_places_provider``
dependency override so the suite stays offline while exercising the real
router → provider → mapping path. The stub tests confirm:

- Routes are wired and JWT-gated.
- Canned responses are stable across calls (deterministic — important
  for demo flows that read the response into card metadata).
- Unknown lookups return 404 / empty rather than 500.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from app.config import Settings
from app.inventory.providers.google_places import GooglePlacesProvider
from app.main import app as fastapi_app
from app.routers.integrations.google_places import get_google_places_provider
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def http_client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


# ── Google Places (live, mock-transport) ───────────────────────────────


def _override_places(handler) -> None:
    """Point the router's provider dependency at a ``MockTransport`` provider."""

    def _factory() -> GooglePlacesProvider:
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, timeout=5.0)
        settings = Settings(
            google_places_base_url="https://places.googleapis.com",
            google_places_api_key="test-places-key",
        )
        return GooglePlacesProvider(client=client, settings=settings)

    fastapi_app.dependency_overrides[get_google_places_provider] = _factory


@pytest.fixture(autouse=True)
def _clear_places_override() -> Iterator[None]:
    yield
    fastapi_app.dependency_overrides.pop(get_google_places_provider, None)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_DIR / name).read_text())


def test_google_places_search_maps_results(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    fixture = _load_fixture("google_places_searchtext.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/places:searchText"
        return httpx.Response(200, json=fixture)

    _override_places(handler)
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "Tokyo"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    # All three fixture places carry geo → three summaries.
    assert len(results) == 3
    names = {r["name"] for r in results}
    assert "Sushi Saito" in names
    first = next(r for r in results if r["name"] == "Sushi Saito")
    assert first["place_id"] == "ChIJ87Sl-zaLGGARsNzac9NJ2Lc"
    assert first["location"]["lat"] == pytest.approx(35.6647321)
    assert "restaurant" in first["types"]


def test_google_places_search_forwards_location_bias(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"places": []})

    _override_places(handler)
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "sushi", "near": {"lat": 35.66, "lng": 139.73}, "radius_m": 1200},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"results": []}
    circle = captured["body"]["locationBias"]["circle"]
    assert circle["center"] == {"latitude": 35.66, "longitude": 139.73}
    assert circle["radius"] == pytest.approx(1200.0)


def test_google_places_search_blank_query_empty(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A whitespace-only query is a no-op (no upstream call), not a 400 —
    mirrors how Text Search treats a blank input.
    """
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"places": []})

    _override_places(handler)
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"results": []}
    assert called["n"] == 0


def test_google_places_details_returns_full_record(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    fixture = _load_fixture("google_places_details.json")
    place_id = fixture["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/places/{place_id}"
        return httpx.Response(200, json=fixture)

    _override_places(handler)
    resp = http_client.get(
        f"/integrations/google-places/details/{place_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["place_id"] == place_id
    assert body["name"] == "Fushimi Inari Taisha"
    assert "tourist_attraction" in body["types"]
    # New-API photo refs are resource names, surfaced as photo_reference.
    assert body["photos"][0]["photo_reference"].startswith("places/")
    assert body["opening_hours"]


def test_google_places_details_404_for_unknown(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    _override_places(handler)
    resp = http_client.get(
        "/integrations/google-places/details/missing-id",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "place_not_found"


def test_google_places_details_502_on_upstream_error(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    _override_places(handler)
    resp = http_client.get(
        "/integrations/google-places/details/abc",
        headers=auth_headers,
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "place_upstream_error"


def test_google_places_requires_auth(http_client: TestClient) -> None:
    """JWT middleware blocks unauthenticated calls."""
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "Aman"},
    )
    assert resp.status_code == 401


# ── Weather ───────────────────────────────────────────────────────────


def test_weather_forecast_is_deterministic(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Same lat/lng/date returns the same forecast across calls so demo
    flows reading the response into a free_time card don't flicker.
    """
    params = {"lat": 35.6762, "lng": 139.6503, "date": "2026-05-15"}
    first = http_client.get(
        "/integrations/weather/forecast",
        params=params,
        headers=auth_headers,
    )
    second = http_client.get(
        "/integrations/weather/forecast",
        params=params,
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert first.json() == second.json()


def test_weather_forecast_validates_lat_bounds(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Lat must be [-90, 90] — a real client-side typo (e.g. swapping
    lat/lng) shouldn't blow up the stub silently.
    """
    resp = http_client.get(
        "/integrations/weather/forecast",
        params={"lat": 200.0, "lng": 0.0, "date": "2026-05-15"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_weather_forecast_summary_mentions_temperature(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.get(
        "/integrations/weather/forecast",
        params={"lat": 0.0, "lng": 0.0, "date": "2026-06-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # Sanity: high >= low.
    assert body["temp_c_high"] >= body["temp_c_low"]
    # Summary mentions the high temp.
    assert str(round(body["temp_c_high"])) in body["summary"]


# ── Flight status ─────────────────────────────────────────────────────


def test_flight_status_returns_canned_for_dl275(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.get(
        "/integrations/flight-status/DL275",
        params={"date": "2026-05-15"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["flight_code"] == "DL275"
    assert body["flight_date"] == "2026-05-15"
    assert body["status"] == "scheduled"
    assert body["aircraft"] == "Airbus A350-900"
    assert body["gate"] == "A38"
    # Departure 15:25 PDT, arrival 18:40 JST next-day.
    assert "15:25" in body["scheduled_departure"]
    assert "2026-05-16" in body["scheduled_arrival"]


def test_flight_status_404_for_unknown_code(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.get(
        "/integrations/flight-status/UA1234",
        params={"date": "2026-05-15"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "flight_not_found"


def test_flight_status_case_insensitive_code(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """``dl275`` and ``DL275`` resolve to the same canned record."""
    lower = http_client.get(
        "/integrations/flight-status/dl275",
        params={"date": "2026-05-15"},
        headers=auth_headers,
    )
    upper = http_client.get(
        "/integrations/flight-status/DL275",
        params={"date": "2026-05-15"},
        headers=auth_headers,
    )
    assert lower.status_code == 200
    assert upper.status_code == 200
    assert lower.json() == upper.json()
