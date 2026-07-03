"""HS256-signed tokens that gate the public Places photo proxy.

A Places (New) photo is a resource *name* (``places/…/photos/…``), not a URL;
rendering it as an image needs a keyed ``…/media`` fetch, and the API key must
stay server-side. The proxy route ``GET /integrations/google-places/photo``
does that fetch — but a browser ``<img>`` tag cannot send an ``Authorization``
header, so the route is whitelisted from the Supabase JWT middleware. The
signed token is therefore the route's *only* gate:

* It binds exactly one photo resource name (``ref``), so a leaked token can't
  be retargeted to pull arbitrary photos on our Places bill.
* ``aud="places-photo"`` lets the verifier reject any token minted for another
  purpose (e.g. a Supabase JWT or an agent token that somehow reaches the route).
* It carries an ``exp`` so a leaked token eventually dies. The TTL is long
  (a year by default) because the token is minted at card-build time and
  persisted in node metadata — it has to outlive the inventory cache.

The signing secret falls back to ``agent_token_signing_secret`` when a
dedicated ``places_photo_signing_secret`` isn't set, so local dev works
without extra provisioning. With neither configured, :func:`mint_photo_token`
returns ``None`` (the caller simply omits the photo URL and the card falls back
to its tint stub) and :func:`verify_photo_token` fails closed.
"""

from __future__ import annotations

import time

import jwt

from app.config import Settings, get_settings

_AUDIENCE = "places-photo"
_ISSUER = "ov-black-api"
_ALGORITHM = "HS256"


class PhotoTokenError(Exception):
    """Verification failure. ``reason`` is a stable short string the route
    maps to a generic 404 — reasons are never leaked to the caller."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _secret(settings: Settings) -> str | None:
    """The effective signing secret, or ``None`` when signing is disabled."""
    return settings.places_photo_signing_secret or settings.agent_token_signing_secret or None


def mint_photo_token(
    ref: str,
    *,
    settings: Settings | None = None,
    ttl_seconds: int | None = None,
) -> str | None:
    """Mint a signed token binding the photo resource name ``ref``.

    Returns ``None`` — not an error — when no signing secret is configured or
    ``ref`` is empty, so the card-mapping layer can simply omit the photo URL.
    """
    settings = settings or get_settings()
    secret = _secret(settings)
    if not secret or not ref:
        return None

    ttl = ttl_seconds if ttl_seconds is not None else settings.places_photo_token_ttl_seconds
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "ref": ref,
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def verify_photo_token(token: str, *, settings: Settings | None = None) -> str:
    """Validate a photo token and return the bound photo resource name.

    Raises :class:`PhotoTokenError` on any failure (no secret, expired, wrong
    audience/issuer, bad signature, missing ``ref``).
    """
    settings = settings or get_settings()
    secret = _secret(settings)
    if not secret:
        raise PhotoTokenError("not_configured")

    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise PhotoTokenError("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise PhotoTokenError("invalid_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise PhotoTokenError("invalid_issuer") from exc
    except jwt.InvalidTokenError as exc:
        raise PhotoTokenError("invalid_token") from exc

    ref = decoded.get("ref")
    if not isinstance(ref, str) or not ref:
        raise PhotoTokenError("missing_ref")
    return ref
