"""Coverage for POST /auth/login and the login service.

Two layers, mirroring ``test_invites.py``:

1. Router tests — exercise the HTTP contract with ``request_login_link``
   stubbed so we can drive each outcome without a live Supabase. We care
   about status codes, response shape, public-path whitelisting, and the
   enumeration-collapse guarantee.
2. Service tests — exercise :func:`request_login_link` with
   ``generate_magic_link`` monkey-patched so we can assert the
   ``create_user=False`` wire and the SupabaseAdminError classification
   without touching httpx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from app.services import login as login_service
from app.services.login import LoginOutcome, request_login_link
from app.services.supabase_admin import MagicLinkIssued, SupabaseAdminError
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    pass


# --- Router-level tests -----------------------------------------------------


@pytest.fixture()
def stub_login_ok(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record emails that would have received a sign-in link."""
    sent: list[str] = []

    async def _fake(email: str) -> login_service.LoginResult:
        sent.append(email)
        return login_service.LoginResult(LoginOutcome.OK)

    monkeypatch.setattr(
        "app.routers.auth.request_login_link",
        _fake,
    )
    return sent


@pytest.fixture()
def stub_login_no_account(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Simulate an unknown email — Supabase refused with 4xx."""
    attempted: list[str] = []

    async def _fake(email: str) -> login_service.LoginResult:
        attempted.append(email)
        return login_service.LoginResult(LoginOutcome.NO_ACCOUNT)

    monkeypatch.setattr(
        "app.routers.auth.request_login_link",
        _fake,
    )
    return attempted


@pytest.fixture()
def stub_login_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(email: str) -> login_service.LoginResult:
        return login_service.LoginResult(LoginOutcome.UPSTREAM_UNAVAILABLE)

    monkeypatch.setattr(
        "app.routers.auth.request_login_link",
        _fake,
    )


def test_login_is_publicly_reachable_without_jwt(
    client: TestClient,
    stub_login_ok: list[str],
) -> None:
    # Like /auth/redeem-invite, this is the front door — it must not require
    # a JWT (the user doesn't have one yet).
    resp = client.post("/auth/login", json={"email": "advisor@example.com"})
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_login_ok == ["advisor@example.com"]


def test_login_ok_returns_204_no_body(
    client: TestClient,
    stub_login_ok: list[str],
) -> None:
    resp = client.post("/auth/login", json={"email": "user@example.com"})
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_login_ok == ["user@example.com"]


def test_login_unknown_email_collapses_to_204(
    client: TestClient,
    stub_login_no_account: list[str],
) -> None:
    # Enumeration guarantee: unknown email is indistinguishable from
    # "link sent" — same 204, no body. Otherwise an attacker could probe
    # which addresses have accounts.
    resp = client.post("/auth/login", json={"email": "nobody@example.com"})
    assert resp.status_code == 204
    assert resp.content == b""
    assert stub_login_no_account == ["nobody@example.com"]


def test_login_upstream_failure_returns_502(
    client: TestClient,
    stub_login_upstream_unavailable: None,
) -> None:
    # Transient Supabase outages surface so the UI can tell the user to
    # retry instead of silently swallowing. This is the one shape distinct
    # from 204 — it means "we couldn't even try", not "we tried and
    # silently declined".
    resp = client.post("/auth/login", json={"email": "user@example.com"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "auth_upstream_unavailable"


def test_login_malformed_payload_returns_422(
    client: TestClient,
    stub_login_ok: list[str],
) -> None:
    # Missing email
    resp = client.post("/auth/login", json={})
    assert resp.status_code == 422
    # Invalid email string
    resp2 = client.post("/auth/login", json={"email": "not-an-email"})
    assert resp2.status_code == 422
    assert stub_login_ok == []


# --- Service-level tests ----------------------------------------------------


@pytest.mark.asyncio
async def test_service_ok_path_calls_generate_with_create_user_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake(email: str, **kwargs: Any) -> MagicLinkIssued:
        calls.append({"email": email, **kwargs})
        return MagicLinkIssued(email=email, action_link="")

    monkeypatch.setattr(login_service, "generate_magic_link", _fake)

    result = await request_login_link("user@example.com")
    assert result.outcome is LoginOutcome.OK
    assert len(calls) == 1
    # The whole point of this service vs. invite redemption: create_user=False
    # so a typo'd email never silently provisions an account.
    assert calls[0]["create_user"] is False
    assert calls[0]["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_service_empty_email_is_no_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        nonlocal called
        called = True
        return MagicLinkIssued(email=email, action_link="")

    monkeypatch.setattr(login_service, "generate_magic_link", _fake)

    result = await request_login_link("   ")
    assert result.outcome is LoginOutcome.NO_ACCOUNT
    # Don't burn a Supabase call on an empty string.
    assert called is False


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
@pytest.mark.asyncio
async def test_service_4xx_rejection_collapses_to_no_account(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_rejected", status_code=status_code)

    monkeypatch.setattr(login_service, "generate_magic_link", _fake)
    result = await request_login_link("unknown@example.com")
    assert result.outcome is LoginOutcome.NO_ACCOUNT


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
@pytest.mark.asyncio
async def test_service_5xx_rejection_is_upstream_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_rejected", status_code=status_code)

    monkeypatch.setattr(login_service, "generate_magic_link", _fake)
    result = await request_login_link("user@example.com")
    assert result.outcome is LoginOutcome.UPSTREAM_UNAVAILABLE


@pytest.mark.asyncio
async def test_service_network_error_is_upstream_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # status_code=None on the SupabaseAdminError means "pre-response failure"
    # (httpx raised before we got anything back). Treat as upstream hiccup.
    async def _fake(email: str, **_kwargs: Any) -> MagicLinkIssued:
        raise SupabaseAdminError("supabase_admin_unreachable")

    monkeypatch.setattr(login_service, "generate_magic_link", _fake)
    result = await request_login_link("user@example.com")
    assert result.outcome is LoginOutcome.UPSTREAM_UNAVAILABLE
