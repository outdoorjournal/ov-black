"""HTTP client the tools use to call the FastAPI backend.

The Supabase JWT carried on the payload is stored in a contextvar so each
tool function can set ``Authorization: Bearer <jwt>`` without plumbing
the token through every call signature. The entrypoint (app.py) sets the
contextvar before invoking the agent and resets it in a ``finally``.

Every tool call resolves the client by the JWT claim on the API side —
no client_id is sent, matching the ``require_user`` gate pattern. Tools
that operate on a specific itinerary / node pass the id as a path param.

Errors map to ``BackendError`` with a short ``reason`` string (matching
the FastAPI ``outcome`` vocabulary where possible). The Strands agent
will surface the exception as a tool error and the model will narrate it
to the user; we do not try to be clever inside the tool.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any

import httpx

from agent.config import get_settings


jwt_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_jwt", default=None
)
"""Forwarded Supabase JWT for the current turn. Set by the entrypoint."""


agent_token_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_token", default=None
)
"""Per-session HS256 token for backend-only ``/agent/*`` routes.

Distinct from :data:`jwt_ctx` — the user JWT keeps its narrower scope
(itineraries the traveler owns); the agent token unlocks Dossier + OSINT
reads + private fact writes that the traveler must not be able to call.
"""


# Stashed so individual tools can read the itinerary pin without plumbing.
pin_ctx: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "agent_pin",
    default={
        "client_id": None,
        "itinerary_id": None,
        "actor_kind": "user",
        "audience": "traveler",
    },
)


class BackendError(Exception):
    """Domain error from a backend HTTP call.

    ``reason`` is either the FastAPI ``outcome`` string (e.g. ``LOCKED``,
    ``client_not_found``) when the response has a structured ``detail``
    field, or a stable fallback derived from the HTTP status / class name
    when it does not. Strands surfaces exceptions to the model as tool
    errors; keeping ``reason`` short lets the model reason about retry
    vs. narrate-the-failure.
    """

    def __init__(self, *, status: int | None, reason: str) -> None:
        super().__init__(f"{status or 'network'}: {reason}")
        self.status = status
        self.reason = reason


def _auth_headers() -> dict[str, str]:
    jwt = jwt_ctx.get()
    if not jwt:
        raise BackendError(status=None, reason="missing_auth")
    return {"Authorization": f"Bearer {jwt}"}


def _agent_auth_headers() -> dict[str, str]:
    """Authorization header carrying the per-session agent token.

    Used only by tools that hit ``/agent/*`` (Dossier + Profile + OSINT
    context, agent-side fact writes). All other tools keep using
    :func:`_auth_headers` so they continue to act on the user's behalf.
    """
    token = agent_token_ctx.get()
    if not token:
        raise BackendError(status=None, reason="missing_agent_token")
    return {"Authorization": f"Bearer {token}"}


@dataclass(slots=True)
class _ClientHolder:
    client: httpx.AsyncClient | None = None


_holder = _ClientHolder()


def _client() -> httpx.AsyncClient:
    """Lazy-initialize one AsyncClient per process.

    AgentCore runs a long-lived HTTP process; reusing a single client
    lets connections pool and keep-alive persist. We don't close it —
    process exit handles that.
    """
    if _holder.client is None:
        settings = get_settings()
        _holder.client = httpx.AsyncClient(
            base_url=settings.backend_base_url,
            timeout=settings.backend_timeout_seconds,
        )
    return _holder.client


async def get_json(path: str, *, params: dict | None = None) -> Any:
    """GET a path, return decoded JSON, raise :class:`BackendError` on failure."""
    try:
        resp = await _client().get(path, params=params, headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def post_json(path: str, *, json: dict | None = None) -> Any:
    """POST JSON, return decoded JSON, raise :class:`BackendError` on failure."""
    try:
        resp = await _client().post(path, json=json or {}, headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def patch_json(path: str, *, json: dict | None = None) -> Any:
    """PATCH JSON, return decoded JSON, raise :class:`BackendError` on failure."""
    try:
        resp = await _client().patch(path, json=json or {}, headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def delete_json(path: str) -> Any:
    """DELETE a path, return decoded JSON (or ``None`` on 204), raise on failure."""
    try:
        resp = await _client().delete(path, headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def agent_get_json(path: str, *, params: dict | None = None) -> Any:
    """GET against an ``/agent/*`` route using the per-session agent token."""
    try:
        resp = await _client().get(
            path, params=params, headers=_agent_auth_headers()
        )
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def agent_post_json(path: str, *, json: dict | None = None) -> Any:
    """POST JSON to an ``/agent/*`` route using the per-session agent token."""
    try:
        resp = await _client().post(
            path, json=json or {}, headers=_agent_auth_headers()
        )
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def agent_patch_json(path: str, *, json: dict | None = None) -> Any:
    """PATCH JSON to an ``/agent/*`` route using the per-session agent token."""
    try:
        resp = await _client().patch(
            path, json=json or {}, headers=_agent_auth_headers()
        )
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


async def agent_delete_json(path: str) -> Any:
    """DELETE an ``/agent/*`` route using the per-session agent token."""
    try:
        resp = await _client().delete(path, headers=_agent_auth_headers())
    except httpx.HTTPError as exc:
        raise BackendError(status=None, reason=exc.__class__.__name__) from exc
    return _unwrap(resp)


def _unwrap(resp: httpx.Response) -> Any:
    if 200 <= resp.status_code < 300:
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise BackendError(
                status=resp.status_code, reason="malformed_json"
            ) from exc

    # Extract FastAPI's ``detail`` when available so the agent sees a
    # stable short reason (e.g. ``locked``, ``client_not_found``).
    reason = f"http_{resp.status_code}"
    try:
        body = resp.json()
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            reason = body["detail"]
    except ValueError:
        pass
    raise BackendError(status=resp.status_code, reason=reason)
