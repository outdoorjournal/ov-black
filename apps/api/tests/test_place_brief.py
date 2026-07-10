"""Tests for ``POST /places/brief`` — the place drawer's server-side spine.

Google resolution reuses the shared ``google_places_searchtext.json`` fixture
via a ``MockTransport`` provider (same pattern as test_integrations); the
texture fetches (Factbook + Wikipedia) go through the ``get_texture_client``
dependency override so the suite stays offline end to end.
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
from app.routers.places import get_texture_client
from app.services import place_texture, places_photo_token
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

_FACTBOOK_JAPAN: dict[str, Any] = {
    "Introduction": {"Background": {"text": "<p>Japan opened to the West in 1854.</p>"}},
    "Geography": {
        "Climate": {"text": "varies from tropical in south to cool temperate in north"},
        "Terrain": {"text": "mostly rugged and mountainous"},
    },
    "People and Society": {
        "Languages": {"Languages": {"text": "Japanese"}},
        "Population": {"total": {"text": "123,201,945 (2024 est.)"}},
    },
    "Government": {"Capital": {"name": {"text": "Tokyo"}}},
}

_WIKIPEDIA_SUMMARY: dict[str, Any] = {
    "type": "standard",
    "title": "Sushi Saito",
    "extract": "Sushi Saito is a sushi restaurant in Tokyo, Japan.",
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Sushi_Saito"}},
    "thumbnail": {"source": "https://upload.wikimedia.org/saito.jpg"},
}


@pytest.fixture()
def http_client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    place_texture.reset_texture_caches()
    yield
    place_texture.reset_texture_caches()


@pytest.fixture(autouse=True)
def _photo_signing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the photo-token mint a secret so briefs carry signed photo handles."""
    s = Settings(agent_token_signing_secret="test-agent-token-signing-secret-please-rotate")
    monkeypatch.setattr(places_photo_token, "get_settings", lambda: s)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    fastapi_app.dependency_overrides.pop(get_google_places_provider, None)
    fastapi_app.dependency_overrides.pop(get_texture_client, None)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_DIR / name).read_text())


def _override_places(payload: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    def _factory() -> GooglePlacesProvider:
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, timeout=5.0)
        settings = Settings(
            google_places_base_url="https://places.googleapis.com",
            google_places_api_key="test-places-key",
        )
        return GooglePlacesProvider(client=client, settings=settings)

    fastapi_app.dependency_overrides[get_google_places_provider] = _factory


def _override_texture(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    fastapi_app.dependency_overrides[get_texture_client] = _factory


def _texture_ok(request: httpx.Request) -> httpx.Response:
    if "githubusercontent" in request.url.host:
        assert request.url.path.endswith("/east-n-southeast-asia/ja.json")
        return httpx.Response(200, json=_FACTBOOK_JAPAN)
    if "wikipedia" in request.url.host:
        return httpx.Response(200, json=_WIKIPEDIA_SUMMARY)
    return httpx.Response(404)


def test_brief_resolves_place_with_texture(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _override_places(_load_fixture("google_places_searchtext.json"))
    _override_texture(_texture_ok)

    resp = http_client.post(
        "/places/brief", json={"query": "Sushi Saito Tokyo"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()

    resolved = body["resolved"]
    assert resolved["name"] == "Sushi Saito"
    assert resolved["place_id"] == "ChIJ87Sl-zaLGGARsNzac9NJ2Lc"
    assert resolved["lat"] == pytest.approx(35.6647321)
    assert resolved["lng"] == pytest.approx(139.7339211)
    assert resolved["editorial_summary"]
    assert resolved["maps_url"].startswith("https://www.google.com/maps/search/")
    # The shared fixture carries photos and the signing secret is set, so the
    # brief must carry signed proxy handles — never raw resource names or keys.
    assert resolved["photo_tokens"]
    assert all("photos/" not in t for t in resolved["photo_tokens"])

    factbook = body["factbook"]
    assert factbook["country_name"] == "Japan"
    assert "1854" in factbook["background"]
    assert "<p>" not in factbook["background"]  # markup stripped
    assert factbook["capital"] == "Tokyo"
    assert factbook["population"] == "123,201,945 (2024 est.)"

    wikipedia = body["wikipedia"]
    assert wikipedia["title"] == "Sushi Saito"
    assert wikipedia["url"] == "https://en.wikipedia.org/wiki/Sushi_Saito"
    assert wikipedia["thumbnail_url"] == "https://upload.wikimedia.org/saito.jpg"


def test_brief_unresolvable_place_404s(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _override_places({"places": []})
    _override_texture(lambda request: httpx.Response(500))

    resp = http_client.post(
        "/places/brief", json={"query": "zzz nowhere at all"}, headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "place_not_found"


def test_brief_degrades_when_texture_sources_fail(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _override_places(_load_fixture("google_places_searchtext.json"))
    _override_texture(lambda request: httpx.Response(500))

    resp = http_client.post("/places/brief", json={"query": "Sushi Saito"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"]["name"] == "Sushi Saito"
    assert body["factbook"] is None
    assert body["wikipedia"] is None


def test_brief_drops_wikipedia_disambiguation(
    http_client: TestClient, auth_headers: dict[str, str]
) -> None:
    _override_places(_load_fixture("google_places_searchtext.json"))

    def handler(request: httpx.Request) -> httpx.Response:
        if "wikipedia" in request.url.host:
            return httpx.Response(200, json={**_WIKIPEDIA_SUMMARY, "type": "disambiguation"})
        return httpx.Response(200, json=_FACTBOOK_JAPAN)

    _override_texture(handler)

    resp = http_client.post("/places/brief", json={"query": "Sushi Saito"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["wikipedia"] is None
    assert body["factbook"] is not None


def test_brief_requires_jwt(http_client: TestClient) -> None:
    resp = http_client.post("/places/brief", json={"query": "Kyoto"})
    assert resp.status_code == 401
