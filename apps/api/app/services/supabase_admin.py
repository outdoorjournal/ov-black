"""Thin client for the Supabase Auth admin API (server-side only).

The only call site so far is :func:`generate_magic_link` — used by
``POST /auth/redeem-invite`` to email a magic link to a freshly-redeemed
invite. The service role key flows in from :class:`Settings` (Secrets
Manager in staging/prod, ``.env`` in local dev) and MUST NEVER be logged
or returned to the client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("ov_black.supabase_admin")


class SupabaseAdminError(Exception):
    """Raised when the Supabase admin API is unreachable or rejects a call."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class MagicLinkIssued:
    """Result of a successful magic-link issuance.

    ``action_link`` is intentionally kept server-side — the caller returns
    204 No Content to avoid leaking it to unauthenticated clients.
    """

    email: str
    action_link: str


async def generate_magic_link(
    email: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> MagicLinkIssued:
    """Ask Supabase Auth to issue a magic link for ``email``.

    Wraps ``POST {supabase_url}/auth/v1/admin/generate_link`` with
    ``type=magiclink``. Supabase will deliver the email via its configured
    SMTP (mailpit/inbucket in local dev, the project's SMTP in staging/prod)
    and also return the ``action_link`` in the response body — we capture it
    for tests/observability but never surface it to the HTTP client.
    """
    settings = settings or get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseAdminError("supabase_admin_not_configured")

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/generate_link"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    payload = {"type": "magiclink", "email": email}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # Never include the key or payload in the log — email is OK.
            logger.warning(
                "supabase_admin.network_error",
                extra={"email": email, "error": exc.__class__.__name__},
            )
            raise SupabaseAdminError("supabase_admin_unreachable") from exc
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code >= 400:
        logger.warning(
            "supabase_admin.rejected",
            extra={"email": email, "status": resp.status_code},
        )
        raise SupabaseAdminError(
            "supabase_admin_rejected",
            status_code=resp.status_code,
        )

    body = resp.json()
    action_link = (
        body.get("action_link")
        or (body.get("properties") or {}).get("action_link")
        or ""
    )
    if not isinstance(action_link, str) or not action_link:
        raise SupabaseAdminError("supabase_admin_missing_link")

    logger.info("supabase_admin.magic_link_issued", extra={"email": email})
    return MagicLinkIssued(email=email, action_link=action_link)
