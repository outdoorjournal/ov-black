"""Shared test fixtures.

The auth tests mint signed JWTs with a one-off RSA keypair and inject the
matching JWK into the module-level JWKS cache, so nothing in the suite hits
the network. ``settings_override`` points the Settings singleton at a known
issuer so ``iss`` validation is exercised for real.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app import auth as auth_module
from app.auth import JWKSCache
from app.config import Settings, get_settings
from app.main import app as fastapi_app

TEST_ISSUER = "https://test.supabase.co/auth/v1"
TEST_KID = "test-kid-1"


@pytest.fixture(scope="session")
def rsa_keypair() -> tuple[Any, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def jwk_public(rsa_keypair: tuple[Any, Any]) -> Any:
    """Return the PyJWK the JWKS cache stores for the test keypair."""
    _, public_key = rsa_keypair
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = TEST_KID
    jwk_dict.setdefault("alg", "RS256")
    return jwt.PyJWK(jwk_dict)


@pytest.fixture(autouse=True)
def settings_override() -> Iterator[Settings]:
    """Replace the cached Settings with test-safe Supabase config."""
    get_settings.cache_clear()
    overrides = Settings(
        env="local",
        supabase_url="https://test.supabase.co",
        supabase_jwt_issuer=TEST_ISSUER,
        supabase_jwks_url="https://test.supabase.co/auth/v1/jwks",
        # Stable test-only HS256 key for agent-token mint/verify round-trips.
        # Tests that exercise the agent-token path import this same value.
        agent_token_signing_secret="test-agent-token-signing-secret-please-rotate",
    )

    def _resolver() -> Settings:
        return overrides

    original = get_settings
    # ``get_settings`` is imported by name in app.auth, so monkey-patching the
    # attribute on the module is enough for every call site.
    auth_module.get_settings = _resolver  # type: ignore[assignment]
    try:
        yield overrides
    finally:
        auth_module.get_settings = original  # type: ignore[assignment]
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def jwks_cache_with_test_key(
    jwk_public: Any,
    settings_override: Settings,
) -> Iterator[JWKSCache]:
    """Seed the module JWKS cache with our test public key, no network calls."""
    cache = JWKSCache(settings_override.supabase_jwks_url, ttl_seconds=3600)
    cache._keys_by_kid = {TEST_KID: jwk_public}
    cache._fetched_at = time.monotonic()
    auth_module._jwks_cache = cache
    try:
        yield cache
    finally:
        auth_module.reset_jwks_cache()


def _encode(
    private_key: Any,
    *,
    kid: str = TEST_KID,
    iss: str = TEST_ISSUER,
    sub: str = "user-abc-123",
    email: str | None = "advisor@example.com",
    role: str | None = "authenticated",
    exp_offset: int = 3600,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": iss,
        "sub": sub,
        "iat": now,
        "exp": now + exp_offset,
    }
    if email is not None:
        payload["email"] = email
    if role is not None:
        payload["role"] = role
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture()
def make_token(rsa_keypair: tuple[Any, Any]):
    """Factory fixture — ``make_token(**overrides)`` returns a signed JWT."""
    private_key, _ = rsa_keypair

    def _factory(**overrides: Any) -> str:
        return _encode(private_key, **overrides)

    return _factory


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c
