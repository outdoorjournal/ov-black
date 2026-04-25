"""Unit tests for :mod:`app.services.agent_token` — mint + verify round-trips.

The agent-internal routes rely on :func:`verify_agent_token` rejecting
Supabase JWTs (wrong issuer + audience) and tokens minted with a
different secret. The auth-matrix integration test in
``test_agent_internal_router.py`` exercises the route layer; this module
proves the verifier is strict in isolation.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.config import Settings
from app.services.agent_token import (
    AgentTokenError,
    mint_agent_token,
    verify_agent_token,
)


def _settings(secret: str = "unit-test-secret-please-rotate", ttl: int = 900) -> Settings:
    return Settings(
        env="local",
        agent_token_signing_secret=secret,
        agent_token_ttl_seconds=ttl,
    )


def test_mint_then_verify_roundtrip_returns_same_claims() -> None:
    s = _settings()
    session_id = uuid.uuid4()
    client_id = uuid.uuid4()
    token = mint_agent_token(
        session_id=session_id,
        client_id=client_id,
        agentcore_session_id="ac-session-1",
        settings=s,
    )
    claims = verify_agent_token(token, settings=s)
    assert claims.session_id == session_id
    assert claims.client_id == client_id
    assert claims.agentcore_session_id == "ac-session-1"
    assert claims.expires_at > claims.issued_at


def test_mint_with_empty_secret_raises_not_configured() -> None:
    s = _settings(secret="")
    with pytest.raises(AgentTokenError) as exc:
        mint_agent_token(
            session_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            agentcore_session_id="ac",
            settings=s,
        )
    assert exc.value.reason == "not_configured"


def test_verify_with_wrong_secret_raises_invalid_token() -> None:
    minted = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=_settings(secret="secret-A"),
    )
    with pytest.raises(AgentTokenError) as exc:
        verify_agent_token(minted, settings=_settings(secret="secret-B"))
    assert exc.value.reason == "invalid_token"


def test_verify_rejects_expired_token() -> None:
    s = _settings()
    token = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=s,
        ttl_seconds=1,
    )
    # Fast-forward past the exp by waiting; PyJWT honors a 0s leeway.
    time.sleep(1.5)
    with pytest.raises(AgentTokenError) as exc:
        verify_agent_token(token, settings=s)
    assert exc.value.reason == "expired"


def test_verify_rejects_token_with_wrong_audience() -> None:
    s = _settings()
    payload = {
        "iss": "ov-black-api",
        "aud": "supabase",  # wrong audience
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "session_id": str(uuid.uuid4()),
        "client_id": str(uuid.uuid4()),
        "agentcore_session_id": "ac",
    }
    forged = jwt.encode(payload, s.agent_token_signing_secret, algorithm="HS256")
    with pytest.raises(AgentTokenError) as exc:
        verify_agent_token(forged, settings=s)
    assert exc.value.reason == "invalid_audience"


def test_verify_rejects_token_with_wrong_issuer() -> None:
    s = _settings()
    payload = {
        "iss": "supabase",  # wrong issuer
        "aud": "agent-internal",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "session_id": str(uuid.uuid4()),
        "client_id": str(uuid.uuid4()),
        "agentcore_session_id": "ac",
    }
    forged = jwt.encode(payload, s.agent_token_signing_secret, algorithm="HS256")
    with pytest.raises(AgentTokenError) as exc:
        verify_agent_token(forged, settings=s)
    assert exc.value.reason == "invalid_issuer"
