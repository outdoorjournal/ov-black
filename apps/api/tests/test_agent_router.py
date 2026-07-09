"""Coverage for the /sessions agent surface (M001/S04 T05).

Router-level tests only — the service behaviour is exercised by
``test_agent_service.py``. We stub ``open_or_reuse_session``,
``stream_turn``, ``list_turns``, ``_load_session_with_client``, and
``_actor_for_user`` on the router module so each case exercises exactly
one router responsibility:

- POST /sessions — outcome → 201 / 404 mapping (D015 collapsed shape)
- POST /sessions/{id}/turn — 404 on session miss or wrong caller, 422
  on invalid content, otherwise a StreamingResponse whose body yields
  the scripted SSE frames
- GET /sessions/{id}/turns — 200 on success, 404 on miss / wrong caller

No Postgres, no live Bedrock — the whole file runs on a fresh checkout
and stays offline.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from app.auth import AuthenticatedUser
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Client, SessionAudience, TurnRole
from app.routers import agent as agent_router_module
from app.services.agent import ActorContext, SessionOutcome, TurnOutcome
from fastapi.testclient import TestClient

# ── Test doubles ───────────────────────────────────────────────────────────


@dataclass
class _NoopResult:
    """Mimics the slice of SQLAlchemy Result the router uses."""

    rows: list[Any] = field(default_factory=list)

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalars(self) -> _NoopResult:
        return self

    def all(self) -> list[Any]:
        return list(self.rows)


@dataclass
class FakeSession:
    """Minimal async-session — the router's only query is Profile lookup,
    which we short-circuit by overriding ``_actor_for_user`` in every test.
    """

    async def execute(self, stmt: Any, params: Any = None) -> _NoopResult:
        return _NoopResult([])

    async def commit(self) -> None:  # pragma: no cover
        return None

    async def rollback(self) -> None:  # pragma: no cover
        return None


@pytest.fixture()
def fake_session() -> Iterator[FakeSession]:
    """Override ``get_session`` with a throwaway FakeSession."""
    fake = FakeSession()

    async def _dep() -> AsyncIterator[FakeSession]:
        yield fake

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield fake
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def advisor_sub() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def auth_headers(
    make_token: Callable[..., str],
    advisor_sub: uuid.UUID,
) -> dict[str, str]:
    """Mint a valid JWT so the middleware lets the request through."""
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_sub))}"}


@pytest.fixture()
def override_actor_as_advisor(
    advisor_sub: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> uuid.UUID:
    """Stub ``_actor_for_user`` to return an advisor ActorContext."""

    async def _fake(user: AuthenticatedUser, session: Any) -> ActorContext:
        return ActorContext(user_id=advisor_sub, actor_kind="advisor", actor_id=str(advisor_sub))

    monkeypatch.setattr(agent_router_module, "_actor_for_user", _fake)
    return advisor_sub


def _client_row(
    *,
    owner_id: uuid.UUID,
    email: str = "client@example.com",
    full_name: str = "Jane Traveler",
    client_id: uuid.UUID | None = None,
) -> Client:
    row = Client(owner_id=owner_id, full_name=full_name, email=email)
    row.id = client_id or uuid.uuid4()
    row.created_at = datetime.now(UTC)
    row.updated_at = row.created_at
    row.auth_user_id = None
    return row


class _FakeAgentSession:
    """Drop-in for the AgentSession ORM row the router reads."""

    def __init__(
        self,
        *,
        session_id: uuid.UUID,
        client_id: uuid.UUID,
        agentcore_session_id: str = "ac-sess-xyz",
        seeded_opener: str | None = None,
        audience: SessionAudience = SessionAudience.traveler,
    ) -> None:
        self.id = session_id
        self.client_id = client_id
        self.agentcore_session_id = agentcore_session_id
        self.seeded_opener = seeded_opener
        self.audience = audience


def _fake_turn(
    *,
    turn_index: int,
    role: TurnRole,
    content: str,
    model: str | None = None,
    latency_ms: int | None = None,
    first_token_ms: int | None = None,
    retried: int = 0,
    error_reason: str | None = None,
) -> Any:
    """Build an ORM-shaped object the router's GET handler can read."""

    obj = type("FakeTurn", (), {})()
    obj.id = uuid.uuid4()
    obj.turn_index = turn_index
    obj.role = role
    obj.content = content
    obj.model = model
    obj.latency_ms = latency_ms
    obj.first_token_ms = first_token_ms
    obj.retried = retried
    obj.error_reason = error_reason
    obj.created_at = datetime.now(UTC)
    return obj


# ── POST /sessions ──────────────────────────────────────────────────────────


def test_post_sessions_advisor_owned_client_returns_201(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advisor = override_actor_as_advisor
    client_id = uuid.uuid4()
    session_id = uuid.uuid4()
    itinerary_id = uuid.uuid4()
    agent_sess = _FakeAgentSession(
        session_id=session_id,
        client_id=client_id,
        agentcore_session_id="ac-sess-owned",
    )

    expected_itinerary_id = itinerary_id

    async def _fake_open(
        _factory: Any,
        *,
        actor: ActorContext,
        client_id: uuid.UUID,  # noqa: ARG001
        itinerary_id: uuid.UUID | None = None,  # noqa: ARG001
        seeded_opener: str | None = None,  # noqa: ARG001
        audience: SessionAudience = SessionAudience.traveler,  # noqa: ARG001
        force_new: bool = False,  # noqa: ARG001
    ) -> tuple[SessionOutcome, Any, uuid.UUID | None]:
        assert actor.actor_kind == "advisor"
        assert actor.user_id == advisor
        return SessionOutcome.OK, agent_sess, expected_itinerary_id

    monkeypatch.setattr(agent_router_module, "open_or_reuse_session", _fake_open)

    resp = client.post(
        "/sessions",
        json={"client_id": str(client_id)},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_id"] == str(session_id)
    assert body["agentcore_session_id"] == "ac-sess-owned"
    assert body["itinerary_id"] == str(expected_itinerary_id)


def test_post_sessions_advisor_audience_is_plumbed_and_returned(
    client: TestClient,
    fake_session: FakeSession,  # noqa: ARG001
    override_actor_as_advisor: uuid.UUID,  # noqa: ARG001
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """audience='advisor' reaches the service and rides back on the response."""
    client_id = uuid.uuid4()
    agent_sess = _FakeAgentSession(
        session_id=uuid.uuid4(),
        client_id=client_id,
        audience=SessionAudience.advisor,
    )
    seen: dict[str, SessionAudience] = {}

    async def _fake_open(
        _factory: Any,
        *,
        actor: ActorContext,  # noqa: ARG001
        client_id: uuid.UUID,  # noqa: ARG001
        itinerary_id: uuid.UUID | None = None,  # noqa: ARG001
        seeded_opener: str | None = None,  # noqa: ARG001
        audience: SessionAudience = SessionAudience.traveler,
        force_new: bool = False,  # noqa: ARG001
    ) -> tuple[SessionOutcome, Any, uuid.UUID | None]:
        seen["audience"] = audience
        return SessionOutcome.OK, agent_sess, None

    monkeypatch.setattr(agent_router_module, "open_or_reuse_session", _fake_open)

    resp = client.post(
        "/sessions",
        json={"client_id": str(client_id), "audience": "advisor"},
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert seen["audience"] is SessionAudience.advisor
    assert resp.json()["audience"] == "advisor"


def test_post_sessions_cross_advisor_returns_404(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D015 collapsed shape: CLIENT_NOT_FOUND and FORBIDDEN both land on 404."""
    other_client_id = uuid.uuid4()

    async def _fake_open(
        _factory: Any,
        *,
        actor: ActorContext,
        client_id: uuid.UUID,
        itinerary_id: uuid.UUID | None = None,
        seeded_opener: str | None = None,  # noqa: ARG001
        audience: SessionAudience = SessionAudience.traveler,  # noqa: ARG001
        force_new: bool = False,  # noqa: ARG001
    ) -> tuple[SessionOutcome, Any, uuid.UUID | None]:
        return SessionOutcome.FORBIDDEN, None, None

    monkeypatch.setattr(agent_router_module, "open_or_reuse_session", _fake_open)

    resp = client.post(
        "/sessions",
        json={"client_id": str(other_client_id)},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"


def test_post_sessions_is_idempotent_on_reopen(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive POSTs return the same session_id — service is idempotent."""
    client_id = uuid.uuid4()
    session_id = uuid.uuid4()
    uuid.uuid4()
    agent_sess = _FakeAgentSession(
        session_id=session_id,
        client_id=client_id,
        agentcore_session_id="ac-reuse-1",
    )

    call_count = {"n": 0}

    async def _fake_open(
        _factory: Any,
        *,
        actor: ActorContext,
        client_id: uuid.UUID,
        itinerary_id: uuid.UUID | None = None,
        seeded_opener: str | None = None,  # noqa: ARG001
        audience: SessionAudience = SessionAudience.traveler,  # noqa: ARG001
        force_new: bool = False,  # noqa: ARG001
    ) -> tuple[SessionOutcome, Any, uuid.UUID | None]:
        call_count["n"] += 1
        return SessionOutcome.OK, agent_sess, itinerary_id

    monkeypatch.setattr(agent_router_module, "open_or_reuse_session", _fake_open)

    r1 = client.post("/sessions", json={"client_id": str(client_id)}, headers=auth_headers)
    r2 = client.post("/sessions", json={"client_id": str(client_id)}, headers=auth_headers)

    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["session_id"] == r2.json()["session_id"] == str(session_id)
    assert call_count["n"] == 2


# ── POST /sessions/{id}/turn ────────────────────────────────────────────────


def test_post_turn_happy_path_streams_sse_frames_in_order(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advisor = override_actor_as_advisor
    session_id = uuid.uuid4()
    client_row = _client_row(owner_id=advisor)
    agent_sess = _FakeAgentSession(session_id=session_id, client_id=client_row.id)

    async def _fake_load(session: Any, sid: uuid.UUID) -> tuple[Any, Any]:
        assert sid == session_id
        return agent_sess, client_row

    monkeypatch.setattr(agent_router_module, "_load_session_with_client", _fake_load)

    async def _scripted_stream(
        _factory: Any,
        _runtime: Any,
        *,
        actor: ActorContext,
        session_id: uuid.UUID,
        content: str,
        auth_bearer: str | None = None,
    ) -> AsyncIterator[bytes]:
        assert actor.actor_kind == "advisor"
        assert content == "Plan me a trip."
        yield b'data: {"type":"first_token","ms":120}\n\n'
        yield b'data: {"type":"delta","text":"Hello"}\n\n'
        yield b'data: {"type":"delta","text":" from"}\n\n'
        yield b'data: {"type":"delta","text":" Bedrock"}\n\n'
        yield b'data: {"type":"done","turn_id":"abc","latency_ms":800}\n\n'

    monkeypatch.setattr(agent_router_module, "stream_turn", _scripted_stream)

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"content": "Plan me a trip."},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("cache-control") == "no-cache"

    # Split on SSE blank-line separator and assert frame order.
    frames = [f for f in resp.text.split("\n\n") if f.strip()]
    assert frames[0].startswith('data: {"type":"first_token"')
    assert frames[1].startswith('data: {"type":"delta","text":"Hello"')
    assert frames[2].startswith('data: {"type":"delta","text":" from"')
    assert frames[3].startswith('data: {"type":"delta","text":" Bedrock"')
    assert frames[4].startswith('data: {"type":"done"')


def test_post_turn_empty_content_returns_422(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_counter = {"stream": 0, "load": 0}

    async def _boom_load(*_a: Any, **_k: Any) -> tuple[Any, Any]:
        call_counter["load"] += 1
        return None, None

    async def _boom_stream(*_a: Any, **_k: Any) -> AsyncIterator[bytes]:
        call_counter["stream"] += 1
        yield b""

    monkeypatch.setattr(agent_router_module, "_load_session_with_client", _boom_load)
    monkeypatch.setattr(agent_router_module, "stream_turn", _boom_stream)

    session_id = uuid.uuid4()
    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"content": ""},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    # 422 fires before the handler body runs — neither helper should have
    # been invoked.
    assert call_counter == {"stream": 0, "load": 0}


def test_post_turn_oversized_content_returns_422(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
) -> None:
    session_id = uuid.uuid4()
    too_big = "a" * 10000

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"content": too_big},
        headers=auth_headers,
    )

    assert resp.status_code == 422


def test_post_turn_by_wrong_caller_returns_404_without_streaming(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller is advisor A, the client row belongs to advisor B → 404."""
    other_advisor = uuid.uuid4()
    session_id = uuid.uuid4()
    other_client = _client_row(owner_id=other_advisor)
    agent_sess = _FakeAgentSession(session_id=session_id, client_id=other_client.id)

    async def _fake_load(session: Any, sid: uuid.UUID) -> tuple[Any, Any]:
        return agent_sess, other_client

    call_counter = {"stream": 0}

    async def _boom_stream(*_a: Any, **_k: Any) -> AsyncIterator[bytes]:
        call_counter["stream"] += 1
        yield b""

    monkeypatch.setattr(agent_router_module, "_load_session_with_client", _fake_load)
    monkeypatch.setattr(agent_router_module, "stream_turn", _boom_stream)

    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"content": "hello"},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "session_not_found"
    # Pre-stream auth must short-circuit before stream_turn is invoked.
    assert call_counter["stream"] == 0


def test_post_turn_unknown_session_returns_404(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_load(session: Any, sid: uuid.UUID) -> tuple[Any, Any]:
        return None, None

    monkeypatch.setattr(agent_router_module, "_load_session_with_client", _fake_load)

    session_id = uuid.uuid4()
    resp = client.post(
        f"/sessions/{session_id}/turn",
        json={"content": "hi"},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "session_not_found"


# ── GET /sessions/{id}/turns ────────────────────────────────────────────────


def test_get_turns_returns_ordered_user_then_assistant(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid.uuid4()
    user_turn = _fake_turn(turn_index=0, role=TurnRole.user, content="Plan me a trip")
    asst_turn = _fake_turn(
        turn_index=1,
        role=TurnRole.assistant,
        content="Sure — here are three ideas.",
        model="abcd1234",
        latency_ms=950,
        first_token_ms=180,
    )

    async def _fake_list(
        _session: Any, *, actor: ActorContext, session_id: uuid.UUID, **_paging: Any
    ) -> list[Any]:
        assert actor.actor_kind == "advisor"
        return [user_turn, asst_turn]

    monkeypatch.setattr(agent_router_module, "list_turns", _fake_list)

    resp = client.get(f"/sessions/{session_id}/turns", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["turn_index"] == 0 and body[0]["role"] == "user"
    assert body[1]["turn_index"] == 1 and body[1]["role"] == "assistant"
    assert body[1]["model"] == "abcd1234"
    assert body[1]["latency_ms"] == 950
    assert body[1]["first_token_ms"] == 180
    assert body[0]["retried"] == 0
    assert body[1]["error_reason"] is None


def test_get_turns_wrong_caller_returns_404(
    client: TestClient,
    fake_session: FakeSession,
    override_actor_as_advisor: uuid.UUID,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_list(
        _session: Any, *, actor: ActorContext, session_id: uuid.UUID, **_paging: Any
    ) -> TurnOutcome:
        return TurnOutcome.SESSION_NOT_YOURS

    monkeypatch.setattr(agent_router_module, "list_turns", _fake_list)

    session_id = uuid.uuid4()
    resp = client.get(f"/sessions/{session_id}/turns", headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "session_not_found"


# ── _actor_for_user resolution after JIT profiles upsert (T02) ─────────────


async def test_actor_for_user_resolves_user_with_populated_user_id_after_profile_upsert() -> None:
    """After the T02 profiles upsert writes role='client', a subsequent turn
    request MUST resolve ``_actor_for_user`` to ``actor_kind='user'`` with a
    populated ``user_id`` — not the ``user_id=None`` collapse path.

    Locks in the router-side contract: the T02 upsert closes a gap where a
    client with a backfilled ``clients.auth_user_id`` but no profiles row
    would still surface through _actor_for_user with ``user_id=None`` (safe
    but inconsistent with the rest of the auth grid).
    """
    from app.models import Profile, UserRole
    from app.routers.agent import _actor_for_user

    caller_sub = uuid.uuid4()
    # Profile row exists post-upsert with role='client'.
    profile_row = Profile(id=caller_sub, role=UserRole.client)

    class _ProfileSession:
        """Returns the scripted Profile on the router's Profile SELECT."""

        async def execute(self, _stmt: Any, _params: Any = None) -> _NoopResult:
            return _NoopResult([profile_row])

    user = AuthenticatedUser(
        sub=str(caller_sub),
        email="client@example.com",
        role="authenticated",
        claims={},
    )

    actor = await _actor_for_user(user, _ProfileSession())

    assert actor.actor_kind == "user"
    # Critical invariant: user_id is populated, NOT None.
    assert actor.user_id == caller_sub
    assert actor.actor_id == str(caller_sub)


async def test_actor_for_user_missing_profile_row_still_returns_populated_user_id() -> None:
    """Targeted regression guard: even WITHOUT a profiles row (the
    pre-backfill steady state), a valid sub UUID must still populate
    ``user_id`` on the resulting ActorContext. The T02 plan explicitly calls
    out that today's behavior does this for all users — this test locks it
    so a future refactor cannot silently regress to ``user_id=None``.
    """
    from app.routers.agent import _actor_for_user

    caller_sub = uuid.uuid4()

    class _EmptyProfileSession:
        async def execute(self, _stmt: Any, _params: Any = None) -> _NoopResult:
            return _NoopResult([])  # No profile row.

    user = AuthenticatedUser(
        sub=str(caller_sub),
        email="client@example.com",
        role="authenticated",
        claims={},
    )

    actor = await _actor_for_user(user, _EmptyProfileSession())

    assert actor.actor_kind == "user"
    assert actor.user_id == caller_sub
    assert actor.actor_id == str(caller_sub)
