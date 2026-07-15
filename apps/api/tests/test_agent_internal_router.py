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
from types import SimpleNamespace
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
            # Traveler logistics (0048) — the context endpoint reads these.
            self.favorite_airport: str | None = None
            self.address: str | None = None
            self.preferred_currency: str | None = None

    class _DummyCtx:
        def __init__(self, cid: uuid.UUID) -> None:
            self.client = _DummyClient(cid)
            self.dossier = None
            self.dossier_facts: list[Any] = []
            self.profile_facts: list[Any] = []
            self.osint_facts: list[Any] = []
            self.party_members: list[Any] = []

    async def _fake_load(_session: Any, *, client_id: uuid.UUID, **_kwargs: Any) -> _DummyCtx:
        return _DummyCtx(client_id)

    monkeypatch.setattr(agent_internal_module, "load_agent_context", _fake_load)

    # Default: the session is not pinned to a fork (G3). Individual tests override.
    async def _fake_fork_state(_session: Any, _session_id: Any) -> tuple[bool, str | None, bool]:
        return (False, None, False)

    monkeypatch.setattr(agent_internal_module, "_resolve_session_fork_state", _fake_fork_state)

    # Default: no trip brief set (0033). Individual tests override to assert the
    # brief flows into the AgentContext payload.
    async def _fake_trip_brief(_session: Any, _session_id: Any) -> str | None:
        return None

    monkeypatch.setattr(agent_internal_module, "_resolve_session_trip_brief", _fake_trip_brief)

    # Default: no pinned itinerary → no graph digest (AGT-2). Tests override to
    # assert the digest flows into the AgentContext payload.
    async def _fake_graph_digest(_session: Any, _session_id: Any) -> str | None:
        return None

    monkeypatch.setattr(agent_internal_module, "_resolve_session_graph_digest", _fake_graph_digest)

    async def _fake_pinned_itinerary(_session: Any, _session_id: Any) -> Any:
        return None

    monkeypatch.setattr(
        agent_internal_module, "_resolve_session_pinned_itinerary", _fake_pinned_itinerary
    )

    # Default: the escalation write succeeds onto a fresh thread (AGT-4).
    from datetime import datetime as _dt

    async def _fake_post_thread_message(_session: Any, **kwargs: Any):
        from app.models import Message, ThreadActorKind
        from app.services.messaging import MessagingOutcome

        message = Message(
            id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            author_kind=ThreadActorKind.artemis,
            author_id=None,
            content=kwargs["content"],
            proposed_node_id=None,
            parent_message_id=None,
            created_at=_dt.now(UTC),
            edited_at=None,
        )
        return (MessagingOutcome.OK, message)

    monkeypatch.setattr(
        agent_internal_module, "post_agent_thread_message", _fake_post_thread_message
    )

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

    async def _fake_create_party_member(*_args: Any, **kwargs: Any):
        from app.models import PartyMember

        now = _now()
        return PartyMember(
            id=uuid.uuid4(),
            client_id=kwargs["client_id"],
            full_name=kwargs["payload"].full_name,
            date_of_birth=None,
            nationality=None,
            dietary=kwargs["payload"].dietary,
            medical=None,
            mobility=None,
            loyalty_programs=[],
            emergency_contact={},
            relationship_to_primary=kwargs["payload"].relationship_to_primary,
            is_primary=kwargs["payload"].is_primary,
            notes=None,
            created_by_actor=kwargs["actor"],
            updated_by_actor=kwargs["actor"],
            recorded_by=kwargs["recorded_by"],
            archived_at=None,
            created_at=now,
            updated_at=now,
        )

    async def _fake_update_party_member(*_args: Any, **kwargs: Any):
        from app.models import PartyMember, PartyMemberActor

        payload = kwargs["payload"]
        now = _now()
        # Model an existing member (authored earlier by an advisor) getting
        # patched by the agent: only set fields change; the rest hold.
        return PartyMember(
            id=kwargs["member_id"],
            client_id=kwargs["client_id"],
            full_name=payload.full_name or "Youngest child",
            date_of_birth=payload.date_of_birth,
            nationality=payload.nationality,
            dietary=payload.dietary,
            medical=payload.medical,
            mobility=payload.mobility,
            loyalty_programs=[],
            emergency_contact={},
            relationship_to_primary=payload.relationship_to_primary,
            is_primary=bool(payload.is_primary),
            notes=payload.notes,
            created_by_actor=PartyMemberActor.advisor,
            updated_by_actor=kwargs["actor"],
            recorded_by=None,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(agent_internal_module, "record_agent_profile_fact", _fake_record_profile)
    monkeypatch.setattr(
        agent_internal_module, "record_agent_dossier_inference", _fake_record_dossier
    )
    monkeypatch.setattr(agent_internal_module, "create_party_member", _fake_create_party_member)
    monkeypatch.setattr(agent_internal_module, "update_party_member", _fake_update_party_member)


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
    assert body["party_members"] == []
    # Not a fork by default — the fork-awareness fields are off.
    assert body["is_alternative"] is False
    assert body["baseline_title"] is None
    assert body["reconcile_requested"] is False
    # No brief set by default (0033).
    assert body["trip_brief"] is None


def test_get_context_surfaces_trip_brief(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0033: the pinned itinerary's brief + timing flows into the payload."""

    async def _brief(_session: Any, _session_id: Any) -> str | None:
        return "Trip brief (...):\nGoal: Sailing in Greece\nWhen: 2027-03-18 to 2027-03-25"

    monkeypatch.setattr(agent_internal_module, "_resolve_session_trip_brief", _brief)
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    assert "Sailing in Greece" in resp.json()["trip_brief"]


def test_get_context_surfaces_fork_awareness(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G3: a session pinned to a fork reports is_alternative + baseline_title."""

    async def _fork(_session: Any, _session_id: Any) -> tuple[bool, str | None, bool]:
        return (True, "Japan in Spring", True)

    monkeypatch.setattr(agent_internal_module, "_resolve_session_fork_state", _fork)
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_alternative"] is True
    assert body["baseline_title"] == "Japan in Spring"
    assert body["reconcile_requested"] is True


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


# ── POST /agent/party-members ─────────────────────────────────────────────


def test_post_party_member_with_valid_token_stamps_agent_actor(client: TestClient) -> None:
    resp = client.post(
        "/agent/party-members",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"full_name": "Sarah", "relationship_to_primary": "spouse", "dietary": "vegetarian"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # actor is fixed server-side — the agent cannot claim advisor/traveler authorship.
    assert body["created_by_actor"] == "agent"
    assert body["updated_by_actor"] == "agent"
    assert body["full_name"] == "Sarah"
    assert body["dietary"] == "vegetarian"


def test_post_party_member_without_token_returns_401(client: TestClient) -> None:
    resp = client.post("/agent/party-members", json={"full_name": "Sarah"})
    assert resp.status_code == 401


def test_post_party_member_seats_companion_on_session_itinerary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded companion is attached to the session's trip travelers edge.

    Recording household identity alone left the dashboard chip on "Just you";
    the endpoint now also seats the new member on the pinned itinerary's party.
    """
    itinerary_id = uuid.uuid4()
    attached: list[tuple[uuid.UUID, str]] = []

    async def _pinned(_session: Any, _session_id: Any) -> Any:
        return itinerary_id

    async def _attach(_session: Any, **kwargs: Any) -> Any:
        attached.append((kwargs["itinerary_id"], kwargs["member"].full_name))
        return object()

    monkeypatch.setattr(agent_internal_module, "_resolve_session_pinned_itinerary", _pinned)
    monkeypatch.setattr(agent_internal_module, "attach_member_to_itinerary", _attach)

    resp = client.post(
        "/agent/party-members",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"full_name": "Emma", "relationship_to_primary": "daughter"},
    )
    assert resp.status_code == 201, resp.text
    assert attached == [(itinerary_id, "Emma")]


def test_post_primary_party_member_not_seated_on_itinerary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The account holder is the party's implicit floor — never a companion row."""
    attached: list[Any] = []

    async def _pinned(_session: Any, _session_id: Any) -> Any:
        return uuid.uuid4()

    async def _attach(_session: Any, **kwargs: Any) -> Any:
        attached.append(kwargs)
        return object()

    monkeypatch.setattr(agent_internal_module, "_resolve_session_pinned_itinerary", _pinned)
    monkeypatch.setattr(agent_internal_module, "attach_member_to_itinerary", _attach)

    resp = client.post(
        "/agent/party-members",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"full_name": "The account holder", "is_primary": True},
    )
    assert resp.status_code == 201, resp.text
    assert attached == []


# ── PATCH /agent/party-members/{member_id} ────────────────────────────────


def test_patch_party_member_updates_and_stamps_agent_actor(client: TestClient) -> None:
    """Naming an existing child patches it (actor=agent) rather than duplicating."""
    member_id = uuid.uuid4()
    resp = client.patch(
        f"/agent/party-members/{member_id}",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"full_name": "Quinn"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(member_id)
    assert body["full_name"] == "Quinn"
    # actor is fixed server-side: the edit is attributed to the agent…
    assert body["updated_by_actor"] == "agent"
    # …while a pre-existing member keeps its original author.
    assert body["created_by_actor"] == "advisor"


def test_patch_party_member_unknown_id_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _missing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(agent_internal_module, "update_party_member", _missing)
    resp = client.patch(
        f"/agent/party-members/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"full_name": "Quinn"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "party_member_not_found"}


def test_patch_party_member_without_token_returns_401(client: TestClient) -> None:
    resp = client.patch(f"/agent/party-members/{uuid.uuid4()}", json={"full_name": "Quinn"})
    assert resp.status_code == 401


# ── /agent/trip-travelers (seat/unseat an existing member on THIS trip) ────

# A non-None sentinel standing in for "the member exists"; the 404 test passes
# member=None instead. Module-level so it isn't a call in an argument default.
_A_MEMBER = object()


def _stub_trip_traveler_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    itinerary_id: uuid.UUID | None,
    member: Any = _A_MEMBER,
    roster: list[tuple[Any, Any]] | None = None,
    seated: list[Any] | None = None,
    detached: list[Any] | None = None,
) -> None:
    async def _pinned(_session: Any, _session_id: Any) -> Any:
        return itinerary_id

    async def _get_member(_session: Any, **_kwargs: Any) -> Any:
        return member

    async def _attach(_session: Any, **kwargs: Any) -> Any:
        if seated is not None:
            seated.append(kwargs)
        return object()

    async def _detach(_session: Any, **kwargs: Any) -> bool:
        if detached is not None:
            detached.append(kwargs)
        return True

    async def _list(_session: Any, **_kwargs: Any) -> Any:
        return roster if roster is not None else []

    monkeypatch.setattr(agent_internal_module, "_resolve_session_pinned_itinerary", _pinned)
    monkeypatch.setattr(agent_internal_module, "get_party_member", _get_member)
    monkeypatch.setattr(agent_internal_module, "attach_member_to_itinerary", _attach)
    monkeypatch.setattr(agent_internal_module, "detach_member_from_itinerary", _detach)
    monkeypatch.setattr(agent_internal_module, "list_itinerary_party", _list)


def test_post_trip_traveler_seats_member_and_returns_roster(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    itinerary_id = uuid.uuid4()
    member_id = uuid.uuid4()
    seated: list[Any] = []
    _stub_trip_traveler_deps(
        monkeypatch,
        itinerary_id=itinerary_id,
        seated=seated,
        roster=[(SimpleNamespace(party_member_id=member_id, name="Emma"), None)],
    )

    resp = client.post(
        "/agent/trip-travelers",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"member_id": str(member_id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["itinerary_id"] == str(itinerary_id)
    assert body["travelers"] == [{"member_id": str(member_id), "name": "Emma"}]
    # the attach actually ran, scoped to the session's pinned itinerary
    assert seated and seated[0]["itinerary_id"] == itinerary_id


def test_post_trip_traveler_without_pin_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_trip_traveler_deps(monkeypatch, itinerary_id=None)
    resp = client.post(
        "/agent/trip-travelers",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"member_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "no_pinned_itinerary"}


def test_post_trip_traveler_unknown_member_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_trip_traveler_deps(monkeypatch, itinerary_id=uuid.uuid4(), member=None)
    resp = client.post(
        "/agent/trip-travelers",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"member_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "party_member_not_found"}


def test_post_trip_traveler_without_token_returns_401(client: TestClient) -> None:
    resp = client.post("/agent/trip-travelers", json={"member_id": str(uuid.uuid4())})
    assert resp.status_code == 401


def test_delete_trip_traveler_unseats_and_returns_roster(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    itinerary_id = uuid.uuid4()
    member_id = uuid.uuid4()
    detached: list[Any] = []
    # After removal the roster is empty → the chip falls back to "Just you".
    _stub_trip_traveler_deps(monkeypatch, itinerary_id=itinerary_id, detached=detached, roster=[])

    resp = client.delete(
        f"/agent/trip-travelers/{member_id}",
        headers={"Authorization": f"Bearer {_good_token()}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"itinerary_id": str(itinerary_id), "travelers": []}
    assert detached and detached[0]["member_id"] == member_id


def test_delete_trip_traveler_without_pin_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_trip_traveler_deps(monkeypatch, itinerary_id=None)
    resp = client.delete(
        f"/agent/trip-travelers/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {_good_token()}"},
    )
    assert resp.status_code == 409


def test_delete_trip_traveler_without_token_returns_401(client: TestClient) -> None:
    resp = client.delete(f"/agent/trip-travelers/{uuid.uuid4()}")
    assert resp.status_code == 401


# ── graph digest in GET /agent/context (AGT-2) ────────────────────────────


def test_get_context_surfaces_graph_digest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGT-2: the pinned itinerary's live plan state flows into the payload."""

    async def _digest(_session: Any, _session_id: Any) -> str | None:
        return "Live plan state (auto-refreshed every turn ...):\n- Status: draft"

    monkeypatch.setattr(agent_internal_module, "_resolve_session_graph_digest", _digest)
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    assert "Live plan state" in resp.json()["graph_digest"]


def test_get_context_graph_digest_defaults_none(client: TestClient) -> None:
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    assert resp.json()["graph_digest"] is None


# ── traveler logistics in GET /agent/context (0048) ───────────────────────


def test_get_context_logistics_default_none(client: TestClient) -> None:
    """Unset logistics surface as null — the agent must ask, not assume."""
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["home_airport"] is None
    assert body["home_address"] is None
    assert body["preferred_currency"] is None


def test_get_context_surfaces_logistics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0048: home airport / address / currency flow into the payload."""

    def _load_with_logistics(_session: Any, *, client_id: uuid.UUID, **_kwargs: Any) -> Any:
        client = SimpleNamespace(
            id=client_id,
            full_name="Test Traveler",
            favorite_airport="ASE",
            address="Aspen, CO",
            preferred_currency="USD",
        )
        return SimpleNamespace(
            client=client,
            dossier=None,
            dossier_facts=[],
            profile_facts=[],
            osint_facts=[],
            party_members=[],
        )

    async def _fake_load(_session: Any, *, client_id: uuid.UUID, **kwargs: Any) -> Any:
        return _load_with_logistics(_session, client_id=client_id, **kwargs)

    monkeypatch.setattr(agent_internal_module, "load_agent_context", _fake_load)
    resp = client.get("/agent/context", headers={"Authorization": f"Bearer {_good_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["home_airport"] == "ASE"
    assert body["home_address"] == "Aspen, CO"
    assert body["preferred_currency"] == "USD"


# ── PATCH /agent/logistics (0048) ─────────────────────────────────────────


def test_patch_logistics_persists_and_echoes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A learned home airport is stored and echoed back, no conflicts."""

    async def _fake_record(*_args: Any, **kwargs: Any) -> Any:
        stored = SimpleNamespace(
            favorite_airport=kwargs["home_airport"],
            address=kwargs["home_address"],
            preferred_currency=kwargs["preferred_currency"],
        )
        return SimpleNamespace(client=stored, skipped=[])

    monkeypatch.setattr(agent_internal_module, "record_agent_travel_logistics", _fake_record)
    resp = client.patch(
        "/agent/logistics",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"home_airport": "ase"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["home_airport"] == "ase"  # (upper-casing happens in the service, stubbed here)
    assert body["skipped"] == []


def test_patch_logistics_reports_overwrite_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing, different value is left untouched and surfaced as a conflict."""
    from app.services.facts import LogisticsConflict

    async def _fake_record(*_args: Any, **kwargs: Any) -> Any:
        stored = SimpleNamespace(
            favorite_airport="DEN", address=None, preferred_currency=None
        )
        return SimpleNamespace(
            client=stored,
            skipped=[LogisticsConflict(field="home_airport", existing="DEN", proposed="ASE")],
        )

    monkeypatch.setattr(agent_internal_module, "record_agent_travel_logistics", _fake_record)
    resp = client.patch(
        "/agent/logistics",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"home_airport": "ASE"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["home_airport"] == "DEN"  # unchanged — no clobber without confirm
    assert body["skipped"] == [
        {"field": "home_airport", "existing": "DEN", "proposed": "ASE"}
    ]


def test_patch_logistics_rejects_bad_iata(client: TestClient) -> None:
    """A non-3-letter airport is a 422 at the schema boundary."""
    resp = client.patch(
        "/agent/logistics",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"home_airport": "Denver"},
    )
    assert resp.status_code == 422


def test_patch_logistics_without_token_returns_401(client: TestClient) -> None:
    resp = client.patch("/agent/logistics", json={"home_airport": "ASE"})
    assert resp.status_code == 401


# ── POST /agent/thread-message (AGT-4) ────────────────────────────────────


def test_post_thread_message_with_valid_token_returns_artemis_message(
    client: TestClient,
) -> None:
    resp = client.post(
        "/agent/thread-message",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"content": "Client asks about a private chef evening."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Attribution is pinned server-side — the agent can never post as a human.
    assert body["author_kind"] == "artemis"
    assert body["author_id"] is None
    assert body["content"] == "Client asks about a private chef evening."


def test_post_thread_message_failure_collapses_to_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.messaging import MessagingOutcome

    async def _refused(_session: Any, **_kwargs: Any):
        return (MessagingOutcome.FORBIDDEN, None)

    monkeypatch.setattr(agent_internal_module, "post_agent_thread_message", _refused)
    resp = client.post(
        "/agent/thread-message",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"content": "hello"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "thread_not_found"}


def test_post_thread_message_without_token_returns_401(client: TestClient) -> None:
    resp = client.post("/agent/thread-message", json={"content": "hello"})
    assert resp.status_code == 401


def test_post_thread_message_empty_content_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/agent/thread-message",
        headers={"Authorization": f"Bearer {_good_token()}"},
        json={"content": ""},
    )
    assert resp.status_code == 422
