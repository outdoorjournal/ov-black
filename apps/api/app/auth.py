"""Supabase JWT validation for FastAPI (R017).

Validates RS256-signed tokens issued by Supabase Auth via its JWKS endpoint,
caches keys in-process with a short TTL, and exposes:

- ``verify_jwt_from_header`` — pure function used by the middleware and tests.
- ``jwt_auth_middleware`` — ASGI middleware that enforces auth on every
  non-whitelisted route and attaches the validated principal to
  ``request.state.user``.
- ``AuthenticatedUser`` / ``require_user`` — typed accessors for route handlers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import jwt
from fastapi import Request
from jwt.algorithms import RSAAlgorithm
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

logger = logging.getLogger("ov_black.auth")


PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or wrongly issued."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The principal extracted from a validated Supabase JWT."""

    sub: str
    email: str | None
    role: str | None
    claims: dict[str, Any]


class JWKSCache:
    """In-process JWKS cache with a TTL.

    Supabase rotates signing keys rarely; a short TTL (default 1h) keeps every
    request off the network while still picking up rotations in-bounds. The
    cache is refreshed on a key-id miss before raising, so a rotation does not
    cause a wave of 401s during the TTL window.
    """

    def __init__(self, jwks_url: str, ttl_seconds: int = 3600) -> None:
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._keys_by_kid: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    def clear(self) -> None:
        self._keys_by_kid = {}
        self._fetched_at = 0.0

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) >= self._ttl

    def _refresh(self) -> None:
        if not self._jwks_url:
            raise AuthError("jwks_url_not_configured")
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(self._jwks_url)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise AuthError("jwks_fetch_failed") from exc
        keys = payload.get("keys") or []
        self._keys_by_kid = {
            key["kid"]: RSAAlgorithm.from_jwk(key)
            for key in keys
            if "kid" in key
        }
        self._fetched_at = time.monotonic()

    def get_key(self, kid: str) -> Any:
        if self._is_stale() or kid not in self._keys_by_kid:
            self._refresh()
        if kid not in self._keys_by_kid:
            raise AuthError("unknown_signing_key")
        return self._keys_by_kid[kid]


_jwks_cache: JWKSCache | None = None


def get_jwks_cache(settings: Settings | None = None) -> JWKSCache:
    global _jwks_cache
    settings = settings or get_settings()
    if _jwks_cache is None or _jwks_cache._jwks_url != settings.supabase_jwks_url:
        _jwks_cache = JWKSCache(settings.supabase_jwks_url)
    return _jwks_cache


def reset_jwks_cache() -> None:
    """Test helper — drop the module-level cache between tests."""
    global _jwks_cache
    _jwks_cache = None


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing_authorization_header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthError("malformed_authorization_header")
    return parts[1]


def verify_token(
    token: str,
    *,
    settings: Settings | None = None,
    jwks: JWKSCache | None = None,
) -> AuthenticatedUser:
    """Validate a Supabase JWT string and return the principal.

    Raises ``AuthError`` for any failure mode (malformed header, unknown kid,
    expired, wrong issuer, signature invalid, missing sub).
    """
    settings = settings or get_settings()
    jwks = jwks or get_jwks_cache(settings)

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("malformed_token") from exc

    kid = header.get("kid")
    if not kid:
        raise AuthError("missing_kid")

    try:
        signing_key = jwks.get_key(kid)
    except AuthError:
        raise

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "issuer": settings.supabase_jwt_issuer or None,
        "options": {
            "require": ["exp", "iat", "sub"],
            "verify_aud": False,
        },
    }
    # PyJWT rejects issuer="" as invalid; only pass issuer when configured.
    if not decode_kwargs["issuer"]:
        decode_kwargs.pop("issuer")

    try:
        claims = jwt.decode(token, signing_key, **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token_expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("wrong_issuer") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid_token") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("missing_sub")

    role = claims.get("role")
    if role is not None and not isinstance(role, str):
        role = None
    email = claims.get("email")
    if email is not None and not isinstance(email, str):
        email = None

    return AuthenticatedUser(sub=sub, email=email, role=role, claims=claims)


def verify_jwt_from_request(request: Request) -> AuthenticatedUser:
    """Extract and verify the bearer token on ``request``.

    Caller is responsible for handling ``AuthError`` — the middleware turns it
    into a 401 JSON response; route dependencies can do the same.
    """
    token = _extract_bearer(request.headers.get("authorization"))
    return verify_token(token)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Enforce Supabase JWT validation on every non-public route (R017).

    Whitelisted paths in ``public_paths`` are served without a token — the
    default set covers the ALB health probe and the OpenAPI/Docs surfaces
    needed for T07 client generation. Every other route requires a bearer
    token; on success the principal is attached to ``request.state.user``.
    """

    def __init__(
        self,
        app: Any,
        *,
        public_paths: Iterable[str] = PUBLIC_PATHS,
    ) -> None:
        super().__init__(app)
        self._public_paths = frozenset(public_paths)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        if request.url.path in self._public_paths:
            return await call_next(request)
        try:
            user = verify_jwt_from_request(request)
        except AuthError as exc:
            logger.info(
                "auth.reject",
                extra={"reason": exc.reason, "path": request.url.path},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "unauthorized", "reason": exc.reason},
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user = user
        return await call_next(request)


def require_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency that returns the principal attached by the middleware.

    The middleware guarantees ``request.state.user`` is set on any non-public
    route that reaches a handler, so this is a pure accessor — it does not
    re-validate the token.
    """
    user = getattr(request.state, "user", None)
    if not isinstance(user, AuthenticatedUser):  # pragma: no cover - defensive
        raise AuthError("no_authenticated_user_on_request")
    return user
