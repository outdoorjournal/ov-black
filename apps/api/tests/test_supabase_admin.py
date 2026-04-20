"""Coverage for ``app.services.supabase_admin.generate_invite_link`` (S03 T03).

``generate_magic_link`` (S01) is exercised end-to-end by ``test_invites.py``
via the redeem flow; this file isolates the new ``generate_invite_link``
call and asserts the wire contract directly with an ``httpx.MockTransport``
stub — no live Supabase.

We cover:

- Happy path: request hits ``POST /auth/v1/invite`` with the correct
  ``apikey`` + ``Authorization`` + ``Content-Type`` headers and an
  ``{email, redirect_to, data}`` body; response's ``action_link`` is
  parsed and returned.
- 4xx rejection: maps to ``SupabaseAdminError('supabase_admin_rejected')``
  with the status code preserved.
- 5xx rejection: same error class, upstream status preserved.
- Network error: httpx transport raises → ``supabase_admin_unreachable``.
- Config missing: empty ``supabase_url`` or ``supabase_service_role_key``
  raises ``supabase_admin_not_configured`` before any request is built.
- Redaction: the service-role key never appears in a log record, and the
  returned ``action_link`` never appears in a log record.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.services.supabase_admin import (
    MagicLinkIssued,
    SupabaseAdminError,
    generate_invite_link,
)

# --- Helpers ----------------------------------------------------------------

_STAGING_URL = "https://test.supabase.co"
_SERVICE_KEY = "sr-secret-do-not-log"


def _settings(url: str = _STAGING_URL, key: str = _SERVICE_KEY) -> Settings:
    return Settings(
        env="local",
        supabase_url=url,
        supabase_service_role_key=key,
    )


def _mock_client(
    handler: "Any",
) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# --- Happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_invite_link_posts_to_invite_endpoint_with_admin_auth() -> (
    None
):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"action_link": "https://test.supabase.co/auth/v1/verify?..."},
        )

    async with _mock_client(handler) as client:
        result = await generate_invite_link(
            "client@example.com",
            "https://app.example.com/auth/callback?next=/command-center",
            settings=_settings(),
            client=client,
        )

    assert isinstance(result, MagicLinkIssued)
    assert result.email == "client@example.com"
    assert result.action_link.startswith("https://test.supabase.co/")

    # Wire contract: exact endpoint, method, headers, body shape.
    assert captured["method"] == "POST"
    assert captured["url"] == f"{_STAGING_URL}/auth/v1/invite"
    # Headers: apikey + Authorization: Bearer + Content-Type: application/json.
    assert captured["headers"]["apikey"] == _SERVICE_KEY
    assert captured["headers"]["authorization"] == f"Bearer {_SERVICE_KEY}"
    assert captured["headers"]["content-type"] == "application/json"
    # Body: email + redirect_to + (optional) data empty dict.
    assert captured["body"]["email"] == "client@example.com"
    assert (
        captured["body"]["redirect_to"]
        == "https://app.example.com/auth/callback?next=/command-center"
    )
    assert captured["body"].get("data") == {}


@pytest.mark.asyncio
async def test_generate_invite_link_parses_nested_properties_action_link() -> (
    None
):
    # Supabase's admin API sometimes nests action_link under "properties".
    # The S01 magic-link helper handles both shapes; the invite helper
    # must do the same so staging/local behaviour is aligned.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"properties": {"action_link": "https://nested/link"}},
        )

    async with _mock_client(handler) as client:
        result = await generate_invite_link(
            "a@b.com",
            "https://app/callback",
            settings=_settings(),
            client=client,
        )
    assert result.action_link == "https://nested/link"


# --- Error paths ------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_invite_link_maps_4xx_to_supabase_admin_rejected() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"msg": "invalid redirect_to"})

    async with _mock_client(handler) as client:
        with pytest.raises(SupabaseAdminError) as exc_info:
            await generate_invite_link(
                "a@b.com",
                "https://app/callback",
                settings=_settings(),
                client=client,
            )
    assert exc_info.value.reason == "supabase_admin_rejected"
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_invite_link_maps_5xx_to_supabase_admin_rejected() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"msg": "upstream down"})

    async with _mock_client(handler) as client:
        with pytest.raises(SupabaseAdminError) as exc_info:
            await generate_invite_link(
                "a@b.com",
                "https://app/callback",
                settings=_settings(),
                client=client,
            )
    assert exc_info.value.reason == "supabase_admin_rejected"
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_generate_invite_link_maps_network_error_to_unreachable() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _mock_client(handler) as client:
        with pytest.raises(SupabaseAdminError) as exc_info:
            await generate_invite_link(
                "a@b.com",
                "https://app/callback",
                settings=_settings(),
                client=client,
            )
    assert exc_info.value.reason == "supabase_admin_unreachable"
    # Network errors are pre-response, so no upstream status code exists.
    assert exc_info.value.status_code is None


@pytest.mark.asyncio
async def test_generate_invite_link_requires_supabase_url() -> None:
    with pytest.raises(SupabaseAdminError) as exc_info:
        await generate_invite_link(
            "a@b.com",
            "https://app/callback",
            settings=_settings(url=""),
        )
    assert exc_info.value.reason == "supabase_admin_not_configured"


@pytest.mark.asyncio
async def test_generate_invite_link_requires_service_role_key() -> None:
    with pytest.raises(SupabaseAdminError) as exc_info:
        await generate_invite_link(
            "a@b.com",
            "https://app/callback",
            settings=_settings(key=""),
        )
    assert exc_info.value.reason == "supabase_admin_not_configured"


@pytest.mark.asyncio
async def test_generate_invite_link_missing_action_link_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"msg": "no link here"})

    async with _mock_client(handler) as client:
        with pytest.raises(SupabaseAdminError) as exc_info:
            await generate_invite_link(
                "a@b.com",
                "https://app/callback",
                settings=_settings(),
                client=client,
            )
    assert exc_info.value.reason == "supabase_admin_missing_link"


# --- Redaction --------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_invite_link_never_logs_service_key_or_action_link(
    caplog: pytest.LogCaptureFixture,
) -> None:
    action_link = "https://test.supabase.co/auth/v1/verify?token=TOP_SECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"action_link": action_link})

    async with _mock_client(handler) as client:
        with caplog.at_level(logging.DEBUG, logger="ov_black.supabase_admin"):
            await generate_invite_link(
                "a@b.com",
                "https://app/callback",
                settings=_settings(),
                client=client,
            )

    combined = "\n".join(
        record.getMessage() + " " + str(record.__dict__)
        for record in caplog.records
        if record.name == "ov_black.supabase_admin"
    )
    assert _SERVICE_KEY not in combined
    assert action_link not in combined
    # Success event *is* logged — just without those secrets.
    assert any(
        r.message == "supabase_admin.invite_link_issued"
        for r in caplog.records
        if r.name == "ov_black.supabase_admin"
    )


@pytest.mark.asyncio
async def test_generate_invite_link_network_error_log_omits_service_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    async with _mock_client(handler) as client:
        with caplog.at_level(logging.WARNING, logger="ov_black.supabase_admin"):
            with pytest.raises(SupabaseAdminError):
                await generate_invite_link(
                    "a@b.com",
                    "https://app/callback",
                    settings=_settings(),
                    client=client,
                )

    records = [
        r for r in caplog.records if r.name == "ov_black.supabase_admin"
    ]
    assert any(r.message == "supabase_admin.network_error" for r in records)
    for r in records:
        combined = r.getMessage() + " " + str(r.__dict__)
        assert _SERVICE_KEY not in combined
