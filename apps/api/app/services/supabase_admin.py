"""Thin client for the Supabase Auth admin API (server-side only).

Two call sites so far:

- :func:`generate_magic_link` — used by ``POST /auth/redeem-invite`` to
  email a magic link to a freshly-redeemed invite (S01).
- :func:`generate_invite_link` — used by ``POST /clients`` to email a
  Supabase ``inviteUserByEmail`` magic link to a brand-new client (S03).

The service role key flows in from :class:`Settings` (Secrets Manager
in staging/prod, ``.env`` in local dev) and MUST NEVER be logged or
returned to the client. The returned ``action_link`` MUST NEVER be
logged either — it is a single-use credential that grants login.
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

    ``action_link`` is kept for callers that need it (e.g. ``generate_invite_link``
    below, which hits ``/auth/v1/invite`` and gets one back). The magic-link
    path hits ``/auth/v1/otp``, which delivers the link by email and returns
    an empty body — so ``action_link`` is the empty string on that path. It
    MUST NEVER be logged or surfaced to an unauthenticated client.
    """

    email: str
    action_link: str


async def generate_magic_link(
    email: str,
    *,
    create_user: bool = True,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> MagicLinkIssued:
    """Ask Supabase Auth to email a magic link to ``email``.

    Wraps ``POST {supabase_url}/auth/v1/otp`` with ``type=magiclink`` (the
    default). The invite-redemption path passes ``create_user=True`` so a
    first-time redeemer gets an auth row created on their behalf; the
    sign-in path (``POST /auth/login``) passes ``create_user=False`` so an
    unknown email does not silently provision an account without an invite.

    Unlike ``/admin/generate_link`` (which only *generates* a link and
    returns it), ``/otp`` *delivers* the link via the configured SMTP —
    inbucket/mailpit in local dev, the project's SMTP in staging/prod —
    and returns an empty body.

    ``options.email_redirect_to`` is set to ``<web_origin>/auth/callback`` so
    the link lands on the SSR callback route that finalizes the session. The
    target must be in Supabase's allow-list (``site_url`` or
    ``additional_redirect_urls``) or Supabase silently falls back to
    ``site_url``.
    """
    settings = settings or get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseAdminError("supabase_admin_not_configured")

    # GoTrue's /otp endpoint honors redirect_to only when passed as a query
    # param; a body ``options.email_redirect_to`` is silently ignored and the
    # emailed link falls back to site_url. So the final /auth/callback target
    # rides the URL, not the JSON body.
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/otp"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    params = {"redirect_to": f"{settings.web_origin.rstrip('/')}/auth/callback"}
    payload: dict[str, object] = {"email": email, "create_user": create_user}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await client.post(url, params=params, json=payload, headers=headers)
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

    logger.info("supabase_admin.magic_link_issued", extra={"email": email})
    return MagicLinkIssued(email=email, action_link="")


async def generate_invite_link(
    email: str,
    redirect_to: str,
    *,
    data: dict[str, object] | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> MagicLinkIssued:
    """Ask Supabase Auth to send an invite email (``inviteUserByEmail``).

    Wraps ``POST {supabase_url}/auth/v1/invite`` with the advisor's
    configured ``redirect_to`` target. On success Supabase creates the
    auth user (if absent) and emails them a signup link via the
    configured SMTP; the response body carries the created user but
    does not include an ``action_link`` (only ``/admin/generate_link``
    does). We opportunistically capture an ``action_link`` if the
    deployment's GoTrue returns one, but treat its absence as success
    — the email is what matters.

    ``data`` lands on ``raw_user_meta_data`` for the new auth user and is
    rendered into the email template as ``{{ .Data.<key> }}``. Used to
    surface the OV-side ``invite_code`` so the recipient can fall back to
    typing it manually if the magic link is broken in transit.
    """
    settings = settings or get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseAdminError("supabase_admin_not_configured")

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/invite"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    payload = {"email": email, "redirect_to": redirect_to, "data": data or {}}

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # Never include the key, authorization header, or action_link.
            # Email is OK per the S01 precedent.
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

    try:
        body = resp.json()
    except ValueError:
        body = {}
    raw_link = (
        body.get("action_link")
        or (body.get("properties") or {}).get("action_link")
        or ""
    )
    action_link = raw_link if isinstance(raw_link, str) else ""

    logger.info("supabase_admin.invite_link_issued", extra={"email": email})
    return MagicLinkIssued(email=email, action_link=action_link)
