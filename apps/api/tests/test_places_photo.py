"""Tests for the Places photo proxy: token service + provider resolve + route.

The proxy exists because a Places (New) photo is a resource *name*, not a URL,
and turning it into an image needs a keyed ``…/media`` fetch that must stay
server-side. A browser ``<img>`` tag can't send a bearer header, so the route
is whitelisted from the Supabase JWT middleware and gated instead by an
HS256-signed photo token that binds exactly one photo reference. These tests
prove the three layers in isolation and end-to-end:

- The token verifier is strict (wrong secret / audience / expiry all fail).
- The provider resolves a ref to a keyless CDN URL and caches it.
- The route is public, redirects to that URL, and 404s on any failure.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.inventory.providers.google_places import (
    GooglePlacesProvider,
    reset_photo_url_cache,
)
from app.main import app as fastapi_app
from app.routers.integrations.google_places import get_google_places_provider
from app.services import places_photo_token as photo_token_module
from app.services.agent_token import mint_agent_token
from app.services.places_photo_token import (
    PhotoTokenError,
    mint_photo_token,
    verify_photo_token,
)
from fastapi.testclient import TestClient

_SECRET = "unit-test-photo-secret-please-rotate"
_REF = "places/ChIJ8Rfu99kIAWARRZ5jLrUJ0Hk/photos/AeY30wM-inari-1"
_CDN_URL = "https://lh3.googleusercontent.com/places/inari-hero=s1600"


def _settings(*, photo_secret: str = _SECRET, agent_secret: str = "") -> Settings:
    return Settings(
        env="local",
        places_photo_signing_secret=photo_secret,
        agent_token_signing_secret=agent_secret,
    )


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    """Photo-URL cache + provider override are process-global — reset around
    each test so ordering can't leak a resolved URL or a mock transport."""
    reset_photo_url_cache()
    yield
    reset_photo_url_cache()
    fastapi_app.dependency_overrides.pop(get_google_places_provider, None)


# ── Token service ───────────────────────────────────────────────────────


def test_mint_then_verify_roundtrip_returns_ref() -> None:
    s = _settings()
    token = mint_photo_token(_REF, settings=s)
    assert token is not None
    assert verify_photo_token(token, settings=s) == _REF


def test_mint_falls_back_to_agent_secret_when_no_dedicated_secret() -> None:
    # Local dev sets only the agent secret; the photo token rides on it.
    s = _settings(photo_secret="", agent_secret="agent-fallback-secret")
    token = mint_photo_token(_REF, settings=s)
    assert token is not None
    assert verify_photo_token(token, settings=s) == _REF


def test_mint_returns_none_when_no_secret_configured() -> None:
    assert mint_photo_token(_REF, settings=_settings(photo_secret="", agent_secret="")) is None


def test_mint_returns_none_for_empty_ref() -> None:
    assert mint_photo_token("", settings=_settings()) is None


def test_verify_without_secret_fails_closed() -> None:
    token = mint_photo_token(_REF, settings=_settings())
    assert token is not None
    with pytest.raises(PhotoTokenError) as exc:
        verify_photo_token(token, settings=_settings(photo_secret="", agent_secret=""))
    assert exc.value.reason == "not_configured"


def test_verify_rejects_wrong_secret() -> None:
    token = mint_photo_token(_REF, settings=_settings())
    assert token is not None
    with pytest.raises(PhotoTokenError):
        verify_photo_token(token, settings=_settings(photo_secret="a-different-secret"))


def test_verify_rejects_agent_token_wrong_audience() -> None:
    # An agent token minted with the SAME secret must still be rejected — the
    # audience claim (agent-internal vs places-photo) is the guard, so a token
    # for one purpose can't be replayed against the other.
    s = Settings(
        env="local",
        agent_token_signing_secret=_SECRET,
        places_photo_signing_secret=_SECRET,
    )
    agent = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=s,
    )
    with pytest.raises(PhotoTokenError) as exc:
        verify_photo_token(agent, settings=s)
    assert exc.value.reason in {"invalid_audience", "invalid_token"}


def test_verify_rejects_expired_token() -> None:
    s = _settings()
    token = mint_photo_token(_REF, settings=s, ttl_seconds=-10)
    assert token is not None
    with pytest.raises(PhotoTokenError) as exc:
        verify_photo_token(token, settings=s)
    assert exc.value.reason == "expired"


# ── Provider resolve ────────────────────────────────────────────────────


def _provider(handler: Any, *, api_key: str = "test-places-key") -> GooglePlacesProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = Settings(
        google_places_base_url="https://places.googleapis.com",
        google_places_api_key=api_key,
    )
    return GooglePlacesProvider(client=client, settings=settings)


async def test_resolve_photo_url_returns_keyless_cdn_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.url.path == f"/v1/{_REF}/media"
        assert request.url.params.get("skipHttpRedirect") == "true"
        assert request.headers["X-Goog-Api-Key"] == "test-places-key"
        # No field mask on the media endpoint.
        assert "X-Goog-FieldMask" not in request.headers
        return httpx.Response(200, json={"name": _REF, "photoUri": _CDN_URL})

    provider = _provider(handler)
    try:
        url = await provider.resolve_photo_url(_REF)
    finally:
        await provider.aclose()
    assert url == _CDN_URL
    assert seen == [f"/v1/{_REF}/media"]


async def test_resolve_photo_url_caches_result() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"photoUri": _CDN_URL})

    provider = _provider(handler)
    try:
        first = await provider.resolve_photo_url(_REF)
        second = await provider.resolve_photo_url(_REF)
    finally:
        await provider.aclose()
    assert first == second == _CDN_URL
    assert calls == 1  # second load served from the in-process cache


async def test_resolve_photo_url_returns_none_on_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    provider = _provider(handler)
    try:
        assert await provider.resolve_photo_url(_REF) is None
    finally:
        await provider.aclose()


async def test_resolve_photo_url_returns_none_without_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not hit upstream without a key")

    provider = _provider(handler, api_key="")
    try:
        assert await provider.resolve_photo_url(_REF) is None
    finally:
        await provider.aclose()


# ── Proxy route (public, token-gated) ───────────────────────────────────


def _override_provider(handler: Any) -> None:
    def _factory() -> GooglePlacesProvider:
        return _provider(handler)

    fastapi_app.dependency_overrides[get_google_places_provider] = _factory


def _route_settings() -> Settings:
    return Settings(env="local", places_photo_signing_secret=_SECRET)


def test_photo_route_redirects_to_keyless_url_without_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _route_settings()
    # The route verifies via places_photo_token's own get_settings.
    monkeypatch.setattr(photo_token_module, "get_settings", lambda: s)
    token = mint_photo_token(_REF, settings=s)
    assert token is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/{_REF}/media"
        return httpx.Response(200, json={"photoUri": _CDN_URL})

    _override_provider(handler)

    # No Authorization header — the route is whitelisted; the token IS the gate.
    with TestClient(fastapi_app) as client:
        resp = client.get(
            "/integrations/google-places/photo",
            params={"token": token},
            follow_redirects=False,
        )
    assert resp.status_code == 302, resp.text
    assert resp.headers["location"] == _CDN_URL
    assert "max-age" in resp.headers.get("cache-control", "")


def test_photo_route_rejects_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(photo_token_module, "get_settings", _route_settings)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("bad token must not reach upstream")

    _override_provider(handler)
    with TestClient(fastapi_app) as client:
        resp = client.get(
            "/integrations/google-places/photo",
            params={"token": "not-a-real-token"},
            follow_redirects=False,
        )
    assert resp.status_code == 404


def test_photo_route_404_when_ref_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _route_settings()
    monkeypatch.setattr(photo_token_module, "get_settings", lambda: s)
    token = mint_photo_token(_REF, settings=s)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    _override_provider(handler)
    with TestClient(fastapi_app) as client:
        resp = client.get(
            "/integrations/google-places/photo",
            params={"token": token},
            follow_redirects=False,
        )
    assert resp.status_code == 404
