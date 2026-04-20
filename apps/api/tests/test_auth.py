"""Table-driven coverage of the Supabase JWT middleware (T03 / R017).

Exercises the five cases called out in S01-PLAN for ``/health/authed``:
missing header, malformed header, expired token, wrong issuer, valid token.
Also guards that ``/health`` stays public so the ALB target group can probe
it without a JWT.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient


def test_health_stays_public(client: "TestClient") -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_stays_public(client: "TestClient") -> None:
    # /openapi.json is whitelisted so T07 client codegen can fetch it without
    # minting a service token.
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


AUTHED_PATH = "/health/authed"


@pytest.mark.parametrize(
    ("headers", "expected_reason"),
    [
        ({}, "missing_authorization_header"),
        ({"Authorization": "not-a-bearer-token"}, "malformed_authorization_header"),
        ({"Authorization": "Bearer "}, "malformed_authorization_header"),
        ({"Authorization": "Basic abc"}, "malformed_authorization_header"),
    ],
)
def test_missing_or_malformed_header_rejected(
    client: "TestClient",
    headers: dict[str, str],
    expected_reason: str,
) -> None:
    resp = client.get(AUTHED_PATH, headers=headers)
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"] == "unauthorized"
    assert body["reason"] == expected_reason
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_malformed_jwt_rejected(client: "TestClient") -> None:
    resp = client.get(
        AUTHED_PATH,
        headers={"Authorization": "Bearer not.a.real.jwt"},
    )
    assert resp.status_code == 401
    assert resp.json()["reason"] in {"malformed_token", "invalid_token"}


def test_expired_token_rejected(
    client: "TestClient",
    make_token: "Callable[..., str]",
) -> None:
    # exp_offset negative → issued 10s ago and already expired.
    token = make_token(exp_offset=-10)
    resp = client.get(AUTHED_PATH, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "token_expired"


def test_wrong_issuer_rejected(
    client: "TestClient",
    make_token: "Callable[..., str]",
) -> None:
    token = make_token(iss="https://attacker.example.com/auth/v1")
    resp = client.get(AUTHED_PATH, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["reason"] == "wrong_issuer"


def test_valid_token_passes_and_returns_principal(
    client: "TestClient",
    make_token: "Callable[..., str]",
) -> None:
    token = make_token(sub="user-abc-123", role="authenticated")
    resp = client.get(AUTHED_PATH, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "sub": "user-abc-123", "role": "authenticated"}


def test_token_missing_sub_rejected(
    client: "TestClient",
    make_token: "Callable[..., str]",
) -> None:
    # PyJWT's ``require`` option should reject a token missing ``sub``.
    token = make_token(sub="")
    resp = client.get(AUTHED_PATH, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_token_with_unknown_kid_rejected(
    client: "TestClient",
    make_token: "Callable[..., str]",
) -> None:
    token = make_token(kid="rotated-out-kid")
    resp = client.get(AUTHED_PATH, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    # Unknown kid triggers a JWKS refresh attempt; in the test environment the
    # refresh either fails (no network) or returns no match — either way a 401
    # with a specific reason lands.
    assert resp.json()["reason"] in {"unknown_signing_key", "jwks_fetch_failed"}
