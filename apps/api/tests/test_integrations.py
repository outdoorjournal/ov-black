"""Tests for the third-party integration stubs (Phase 4).

These endpoints are placeholders that return canned data shaped like
the live integrations they'll one day proxy (Google Places, weather,
flight status). The tests confirm:

- Routes are wired and JWT-gated.
- Canned responses are stable across calls (deterministic — important
  for demo flows that read the response into card metadata).
- Unknown lookups return 404 / empty rather than 500.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture()
def http_client() -> "Iterator[TestClient]":
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def auth_headers(make_token: "Callable[..., str]") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"
    }


# ── Google Places ─────────────────────────────────────────────────────


def test_google_places_search_finds_known_query(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "Aman"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["place_id"] == "stub-aman-tokyo"
    assert body["results"][0]["name"] == "Aman Tokyo"


def test_google_places_search_empty_for_unknown_query(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "nowhere-in-particular-xyz"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_google_places_search_blank_query_empty(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A whitespace-only query is a no-op, not a 400 — mirrors how
    real Places "Text Search" handles a blank input.
    """
    resp = http_client.post(
        "/integrations/google-places/search",
        json={"query": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_google_places_details_returns_full_record(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.get(
        "/integrations/google-places/details/stub-fushimi-inari",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["place_id"] == "stub-fushimi-inari"
    assert body["name"] == "Fushimi Inari Taisha"
    assert "tourist_attraction" in body["types"]
    assert body["photos"][0]["photo_reference"]


def test_google_places_details_404_for_unknown(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = http_client.get(
        "/integrations/google-places/details/stub-unknown",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "place_not_found"


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
