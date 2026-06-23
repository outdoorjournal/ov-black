"""Password-grant minting (offline, respx-mocked GoTrue)."""

import httpx
import pytest
import respx

from _helpers import make_jwt
from ovb.auth import TokenStore, mint_jwt, mint_via_password
from ovb.config import Profile
from ovb.errors import AuthError

SB = "http://sb.test"


def _profile(**over: object) -> Profile:
    base: dict[str, object] = {
        "name": "staging",
        "api_url": "http://api.test",
        "supabase_url": SB,
        "anon_key": "anon-123",
        "password": "s3cret",
        "auth_method": "password",
        "default_email": "svc@x.com",
        "default_role": "advisor",
    }
    base.update(over)
    return Profile(**base)  # type: ignore[arg-type]


@respx.mock
def test_mint_via_password_success_sends_anon_key_and_creds() -> None:
    tok = make_jwt(email="svc@x.com")
    route = respx.post(f"{SB}/auth/v1/token").mock(
        return_value=httpx.Response(200, json={"access_token": tok, "token_type": "bearer"})
    )
    out = mint_via_password(
        supabase_url=SB, anon_key="anon-123", email="svc@x.com", password="s3cret"
    )
    assert out == tok
    req = route.calls.last.request
    assert req.headers["apikey"] == "anon-123"
    assert "grant_type=password" in str(req.url)
    assert b'"password"' in req.content  # creds go to Supabase, not our backend


@respx.mock
def test_mint_via_password_bad_creds_surface_clean_reason() -> None:
    respx.post(f"{SB}/auth/v1/token").mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Invalid login credentials"}
        )
    )
    with pytest.raises(AuthError) as exc:
        mint_via_password(supabase_url=SB, anon_key="a", email="x@y.com", password="bad")
    assert "Invalid login credentials" in str(exc.value)


@respx.mock
def test_mint_jwt_routes_password_then_caches() -> None:
    tok = make_jwt()
    route = respx.post(f"{SB}/auth/v1/token").mock(
        return_value=httpx.Response(200, json={"access_token": tok})
    )
    store = TokenStore()
    profile = _profile()
    assert mint_jwt(profile, store=store) == tok
    assert mint_jwt(profile, store=store) == tok  # cache hit
    assert route.call_count == 1


@respx.mock
def test_auto_method_prefers_password_when_set() -> None:
    tok = make_jwt()
    respx.post(f"{SB}/auth/v1/token").mock(
        return_value=httpx.Response(200, json={"access_token": tok})
    )
    assert mint_jwt(_profile(auth_method="auto"), store=TokenStore()) == tok


def test_password_mode_rejects_mismatched_email() -> None:
    with pytest.raises(AuthError) as exc:
        mint_jwt(_profile(), email="other@x.com", store=TokenStore())
    assert "bound to" in str(exc.value)


def test_password_mode_rejects_role_switch() -> None:
    with pytest.raises(AuthError) as exc:
        mint_jwt(_profile(), role="traveler", store=TokenStore())
    assert "role" in str(exc.value)


def test_password_mode_requires_password_and_anon_key() -> None:
    with pytest.raises(AuthError) as exc:
        mint_jwt(_profile(password=None), store=TokenStore())
    assert "no password" in str(exc.value)
    with pytest.raises(AuthError) as exc:
        mint_jwt(_profile(anon_key=None), store=TokenStore())
    assert "anon key" in str(exc.value)


def test_presupplied_jwt_still_wins_over_password() -> None:
    # A profile carrying a verbatim token short-circuits before any grant.
    out = mint_jwt(_profile(jwt="pre.minted.tok"), store=TokenStore())
    assert out == "pre.minted.tok"
