"""HS256-signed per-session tokens for the agent runtime → backend hop.

Minted at ``POST /sessions`` and stashed only in the agent runtime
process — never returned to the browser. The agent presents the token
on calls to the backend-only ``/agent/*`` routes (Dossier + Profile +
OSINT context, private fact writes), which validate it with
:func:`verify_agent_token` instead of going through the Supabase JWT
middleware.

Why a separate token instead of forwarding the client JWT:

* The traveler's JWT must not be able to read Dossier or OSINT.
* The agent runs server-side, so a long-lived service secret would have
  too wide a blast radius if leaked. A 15-minute, session-bound token
  is narrowly scoped to "may read context for *this* client during
  *this* session".
* ``aud="agent-internal"`` lets the verifier cleanly reject any token
  that wasn't minted for this purpose, including a Supabase JWT that
  somehow reaches the route.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import jwt

from app.config import Settings, get_settings

logger = logging.getLogger("ov_black.agent_token")

_AUDIENCE = "agent-internal"
_ISSUER = "ov-black-api"
_ALGORITHM = "HS256"


class AgentTokenError(Exception):
    """Verification or minting failure. ``reason`` is a stable short string."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AgentTokenClaims:
    """The validated claims of an agent token."""

    session_id: uuid.UUID
    client_id: uuid.UUID
    agentcore_session_id: str
    issued_at: int
    expires_at: int


def mint_agent_token(
    *,
    session_id: uuid.UUID,
    client_id: uuid.UUID,
    agentcore_session_id: str,
    settings: Settings | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a fresh HS256 agent token bound to one session + client.

    Raises :class:`AgentTokenError` with reason ``not_configured`` if the
    signing secret is empty (local dev with no agent secret set, or a
    misprovisioned environment) — callers should treat this as a 503.
    """
    settings = settings or get_settings()
    secret = settings.agent_token_signing_secret
    if not secret:
        raise AgentTokenError("not_configured")

    ttl = ttl_seconds if ttl_seconds is not None else settings.agent_token_ttl_seconds
    now = int(time.time())
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "session_id": str(session_id),
        "client_id": str(client_id),
        "agentcore_session_id": agentcore_session_id,
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def verify_agent_token(
    token: str, *, settings: Settings | None = None
) -> AgentTokenClaims:
    """Decode + validate an agent token. Raises :class:`AgentTokenError` on any failure.

    Failures collapse to a short stable ``reason`` string the route
    layer can map to a generic 401 — verification reasons are not leaked
    to the caller.
    """
    settings = settings or get_settings()
    secret = settings.agent_token_signing_secret
    if not secret:
        raise AgentTokenError("not_configured")

    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AgentTokenError("expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise AgentTokenError("invalid_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise AgentTokenError("invalid_issuer") from exc
    except jwt.InvalidTokenError as exc:
        raise AgentTokenError("invalid_token") from exc

    try:
        return AgentTokenClaims(
            session_id=uuid.UUID(decoded["session_id"]),
            client_id=uuid.UUID(decoded["client_id"]),
            agentcore_session_id=str(decoded["agentcore_session_id"]),
            issued_at=int(decoded["iat"]),
            expires_at=int(decoded["exp"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AgentTokenError("malformed_claims") from exc
