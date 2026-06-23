"""Exception hierarchy for the ovb SDK / CLI / harness.

SDK operations raise on failure rather than threading a discriminated result
type through every call (the TS client's ``{ok}`` union is a TypeScript
ergonomic; raising is the Pythonic equivalent and reads cleanly in pytest:
``with pytest.raises(ApiError) as e: ...; assert e.value.status == 403``).
``ApiError`` carries the full structured detail so the CLI can render a crafted
failure and tests can assert on the exact status / reason.
"""

from __future__ import annotations

from typing import Any


class OvbError(Exception):
    """Base class for every error raised by ovb."""


class ConfigError(OvbError):
    """Profile/config resolution failed (unknown profile, missing setting)."""


class AuthError(OvbError):
    """JWT minting failed (mint-jwt.sh non-zero, no token, missing creds)."""


class ApiError(OvbError):
    """A non-2xx response from apps/api.

    ``detail`` is the collapsed reason string the API returns (e.g.
    ``"client_not_found"``, ``"advisor_only"``); ``body`` is the raw decoded
    payload for cases where the caller wants the full validation error.
    """

    def __init__(
        self,
        status: int,
        detail: str,
        *,
        method: str = "",
        path: str = "",
        body: Any = None,
    ) -> None:
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path
        self.body = body
        where = f" ({method} {path})" if path else ""
        super().__init__(f"{status} {detail}{where}")


class TurnError(OvbError):
    """The agent turn stream ended in an ``error`` frame (e.g. upstream_unavailable)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"agent turn failed: {reason}")
