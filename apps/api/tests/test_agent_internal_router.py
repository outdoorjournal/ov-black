"""Auth-matrix tests for the backend-only ``/agent/*`` routes.

The new routes deliberately bypass the Supabase JWT middleware (their
paths live in ``PUBLIC_PATHS``) and validate an HS256 agent token via
:func:`app.routers.agent_internal.require_agent_token`. This test
file pins the gate's behaviour so a future refactor cannot accidentally
let a Supabase client JWT read Dossier or OSINT.

The route bodies (which call into the database) are exercised in
``test_facts_service.py`` once the service-side helpers settle. Here we
isolate the auth gate by overriding the DB-touching dependency (``get_session``)
with a no-op + stubbing the loaders, so each test is a pure auth matrix.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

import jwt
import pytest
from app.config import Settings
from app.main import app as fastapi_app
from app.routers import agent_internal as agent_internal_module
from app.services import agent_token as agent_token_module
from app.services.agent_token import mint_agent_token
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _settings() -> Settings:
    return Settings(
        env="local",
        agent_token_signing_secret="test-agent-token-signing-secret-please-rotate",
        agent_token_ttl_seconds=900,
    )


@pytest.fixture()
def app() -> FastAPI:
    return fastapi_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_load_agent_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the DB read so the auth gate is the only failure surface."""

    class _DummyClient:
        def __init__(self, cid: uuid.UUID) -> None:
            self.id = cid
            self.full_name = "Test Traveler"

    class _DummyCtx:
        def __init__(self, cid: uuid.UUID) -> None:
            self.client = _DummyClient(cid)
            self.dossier = None
            self.dossier_facts: list[Any] = []
            self.profile_facts: list[Any] = []
            self.osint_facts: list[Any] = []

    async def _fake_load(_session: Any, *, client_id: uuid.UUID, **_kwargs: Any) -> _DummyCtx:
        return _DummyCtx(client_id)

    monkeypatch.setattr(agent_internal_module, "load_agent_context", _fake_load)

    # Side-by-side stubs for the two write paths. The stamp the routes
    # validate via DossierFactDetail / ProfileFactDetail expects every
    # timestamp populated, so the stubs fill them eagerly.
    from datetime import datetime

    def _now() -> datetime:
        return datetime.now(UTC)

    async def _fake_record_profile(*_args: Any, **kwargs: Any):
        from app.models import FactSourceKind, ProfileFact

        now = _now()
        return ProfileFact(
            id=uuid.uuid4(),
            client_id=kwargs["client_id"],
            kind=kwargs["kind"],
            text=kwargs["text"],
            source_kind=FactSourceKind.traveler_told,
            source_ref={},
            observed_at=now,
            recorded_by=uuid.uuid4(),
            redacted_at=None,
            redacted_by=None,
            redacted_reason=None,
            created_at=now,
            updated_at=now,
        )

    async def _fake_record_dossier(*_args: Any, **kwargs: Any):
        from app.models import DossierFact, FactSourceKind

        now = _now()
        return DossierFact(
            id=uuid.uuid4(),
            client_id=kwargs["client_id"],
            kind=kwargs["kind"],
            text=kwargs["text"],
            source_kind=FactSourceKind.agent_inferred,
            source_ref={},
            observed_at=now,
            recorded_by=uuid.uuid4(),
            redacted_at=None,
            redacted_by=None,
            redacted_reason=None,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(agent_internal_module, "record_agent_profile_fact", _fake_record_profile)
    monkeypatch.setattr(
        agent_internal_module, "record_agent_dossier_inference", _fake_record_dossier
    )


@pytest.fixture(autouse=True)
def _stub_db_session(app: FastAPI) -> Any:
    """Override get_session so route handlers receive a sentinel object."""
    from app.db import get_session

    async def _empty():
        yield object()

    app.dependency_overrides[get_session] = _empty
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _agent_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force agent_token to use the same secret regardless of caller settings."""
    s = _settings()
    monkeypatch.setattr(agent_token_module, "get_settings", lambda: s)


def _good_token() -> str:
    return mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=_settings(),
    )


# ── GET /agent/context ────────────────────────────────────────────────────


def test_get_context_with_valid_agent_token_returns_200(client: TestClient) -> None:
    resp = client.get(
        "/agent/context",
        headers={"Authorization": f"Bearer {_good_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dossier"] is None
    assert body["dossier_facts"] == []
    assert body["profile_facts"] == []
    assert body["osint_facts"] == []


def test_get_context_with_no_authorization_header_returns_401(client: TestClient) -> None:
    resp = client.get("/agent/context")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "agent_unauthorized"}


def test_get_context_with_non_bearer_authorization_returns_401(client: TestClient) -> None:
    resp = client.get("/agent/context", headers={"Authorization": "Basic xxx"})
    assert resp.status_code == 401


def test_get_context_with_supabase_jwt_returns_401(client: TestClient) -> None:
    """A perfectly valid Supabase RS256 JWT must NOT pass — wrong issuer + audience.

    We forge a token with the *correct* HS256 secret but Supabase-shaped
    claims (issuer, no audience) and confirm the gate rejects it.
    """
    payload = {
        "iss": "https://test.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": 1_000_000,
        "exp": 9_999_999_999,
        "sub": str(uuid.uuid4()),
        "email": "client@example.com",
    }
    forged = jwt.encode(payload, _settings().agent_token_signing_secret, algorithm="HS256")
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_get_context_with_expired_token_returns_401(client: TestClient) -> None:
    s = _settings()
    token = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=s,
        ttl_seconds=1,
    )
    import time

    time.sleep(1.5)
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_get_context_with_wrong_secret_returns_401(client: TestClient) -> None:
    other = Settings(env="local", agent_token_signing_secret="some-other-secret")
    token = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=other,
    )
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ── POST /agent/profile/facts ────────────────────────────────────────────


def test_post_profile_fact_with_valid_token_returns_201(client: TestClient) -> None:
    resp = client.post(
        "/agent/profile/facts",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"kind": "preference", "text": "morning person"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # The endpoint MUST stamp source_kind=traveler_told regardless of payload.
    assert body["source_kind"] == "traveler_told"
    assert body["text"] == "morning person"


def test_post_profile_fact_without_token_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/agent/profile/facts",
        json={"kind": "preference", "text": "morning person"},
    )
    assert resp.status_code == 401


# ── POST /agent/dossier/facts ────────────────────────────────────────────


def test_post_dossier_inference_with_valid_token_returns_201(client: TestClient) -> None:
    resp = client.post(
        "/agent/dossier/facts",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"kind": "passion", "text": "likely values seclusion"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # The endpoint MUST stamp source_kind=agent_inferred regardless of payload.
    assert body["source_kind"] == "agent_inferred"
    assert body["text"] == "likely values seclusion"


def test_post_dossier_inference_without_token_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/agent/dossier/facts",
        json={"kind": "passion", "text": "likely values seclusion"},
    )
    assert resp.status_code == 401
