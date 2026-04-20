"""Unit tests for ``app.services.agent``.

Offline-only. Substitutes a fake async-session + sessionmaker that records
every ``session.add`` / ``commit`` / ``rollback`` call so we can assert
the two-transaction discipline and the field values the service writes.

The test surface covers:
  1. happy path — 3 deltas → 3 delta frames + first_token + done + assistant row
  2. first-call ``AgentRuntimeError`` → one retry succeeds → frames land + retried=1
  3. both attempts fail → crafted fallback frame + role='error' + error_reason
  4. advisor whose owner_id doesn't match client → SESSION_NOT_YOURS fallback, no DB writes for turn
  5. first-token deadline blows through → fallback fires
  6. memory CreateEvent failure → turn completes + WARN + assistant row still written
  7. session open/reuse is idempotent per (client_id, ended_at IS NULL)
  8. redaction sweep — content, prompt, context substrings NEVER appear in any caplog record
  9. turn_index monotonicity — second turn reads max+1
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agent.bedrock import AgentRuntimeError, MockAgentRuntimeClient
from app.agent.prompt import build_system_prompt
from app.config import Settings
from app.models import (
    AgentSession,
    AgentTurn,
    Client,
    Itinerary,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
    TurnRole,
    VoodooDoll,
)
from app.models.client import ContactChannel, GroupType
from app.services.agent import (
    ActorContext,
    SessionOutcome,
    TurnOutcome,
    open_or_reuse_session,
    stream_turn,
)
from app.services import itineraries as itineraries_service

SECRET_NETWORTH = 999999999
SECRET_OSINT = "DO_NOT_LOG_THIS_OSINT"


# ── Test doubles ───────────────────────────────────────────────────────────


@dataclass
class FakeResult:
    """Stand-in for SQLAlchemy ``Result``."""

    rows: list[Any] = field(default_factory=list)

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        if not self.rows:
            raise AssertionError("scalar_one called on empty result")
        return self.rows[0]

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self.rows)

    def first(self) -> Any:
        return self.rows[0] if self.rows else None


@dataclass
class FakeSession:
    """Minimal async-session that lets tests script query returns.

    ``responses`` is a list of callables — each is invoked with the stmt
    (an SQLAlchemy Core/ORM Select) and returns a ``FakeResult``. The
    service calls ``session.execute`` N times; tests script N responders.

    Tests that care about monotonicity drive turn_index through a single
    shared store on the factory.
    """

    factory: "FakeFactory"
    added: list[Any] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    refreshes: int = 0
    commit_raises: BaseException | None = None

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, stmt: Any, params: Any = None) -> FakeResult:
        return self.factory.answer(self, stmt, params)

    def add(self, obj: Any) -> None:
        # Emulate server-side default on AgentSession.id.
        if isinstance(obj, AgentSession) and obj.id is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, AgentTurn) and obj.id is None:
            obj.id = uuid.uuid4()
        # Emulate server-side default on Itinerary / Node / NodeHistory.id.
        if isinstance(obj, Itinerary) and obj.id is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, Node) and obj.id is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, NodeHistory) and obj.id is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.factory.after_add(self, obj)

    async def commit(self) -> None:
        if self.commit_raises is not None:
            exc, self.commit_raises = self.commit_raises, None
            raise exc
        self.commits += 1
        self.factory.after_commit(self)

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshes += 1

    async def flush(self) -> None:
        # Stand-in for AsyncSession.flush — the itineraries service uses it
        # to surface IntegrityError before commit. Tests don't simulate that.
        return None


@dataclass
class FakeFactory:
    """async_sessionmaker stand-in.

    Holds the shared state the service will query through: the seeded
    agent_session / client / voodoo_doll row trio, a running list of
    turn rows (so second-call turn_index lookups see the first turn),
    and a queue of pre-scripted responses for non-data-model execute()
    calls (the FOR UPDATE row lock).
    """

    agent_session: AgentSession | None = None
    client_row: Client | None = None
    doll: VoodooDoll | None = None
    turns: list[AgentTurn] = field(default_factory=list)
    sessions_created: list[FakeSession] = field(default_factory=list)
    open_agent_session_on_reuse: AgentSession | None = None
    # A hook lets tests simulate IntegrityError on a specific commit.
    commit_raise_sequence: list[BaseException | None] = field(default_factory=list)
    # JIT-backfill hooks: email the faked auth.users SELECT should return for a
    # given user_id string (None ⇒ no matching auth.users row). ``auth_update_count``
    # counts UPDATE clients SET auth_user_id statements issued so tests can
    # assert the backfill did / did not run.
    auth_users_emails: dict[str, str] = field(default_factory=dict)
    auth_users_select_raises: BaseException | None = None
    auth_update_count: int = 0
    # Profiles upsert tracking for T02. Each INSERT ... ON CONFLICT DO NOTHING
    # against public.profiles appends its user_id (as str) here.
    # ``profiles_existing_roles`` is the in-memory projection the test writes
    # to simulate pre-existing rows: when the service issues the INSERT, we
    # look up the row by id; present ⇒ ON CONFLICT DO NOTHING is a no-op and
    # the stored role is left untouched; absent ⇒ the row is inserted with
    # role='client'. Tests inspect ``profiles_existing_roles`` after the call
    # to assert role preservation.
    profile_upsert_calls: list[str] = field(default_factory=list)
    profiles_existing_roles: dict[str, str] = field(default_factory=dict)
    # S07 T03 — itinerary state for agent-proposed card persistence. The
    # in-memory ``itineraries`` list is indexed by client_id; ``nodes``
    # accumulates every Node the itineraries service adds via ``session.add``.
    itineraries: list[Itinerary] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    node_histories: list[NodeHistory] = field(default_factory=list)

    def __call__(self) -> FakeSession:
        sess = FakeSession(factory=self)
        if self.commit_raise_sequence:
            sess.commit_raises = self.commit_raise_sequence.pop(0)
        self.sessions_created.append(sess)
        return sess

    def after_add(self, session: FakeSession, obj: Any) -> None:
        if isinstance(obj, AgentTurn):
            self.turns.append(obj)
        elif isinstance(obj, Itinerary):
            self.itineraries.append(obj)
        elif isinstance(obj, Node):
            self.nodes.append(obj)
        elif isinstance(obj, NodeHistory):
            self.node_histories.append(obj)

    def after_commit(self, session: FakeSession) -> None:
        return None

    def answer(
        self,
        session: FakeSession,
        stmt: Any,
        params: Any = None,
    ) -> FakeResult:
        """Route Select statements to the in-memory stand-in rows.

        We inspect the compiled SQL string to decide what the service is
        asking for. This is brittle but keeps the test seam small — no
        need to maintain a full in-memory Select interpreter.
        """
        try:
            sql = str(stmt)
        except Exception:
            sql = ""
        sql_lower = sql.lower()

        # Raw text() SELECT against auth.users for JIT backfill.
        if "auth.users" in sql_lower and "select" in sql_lower:
            if self.auth_users_select_raises is not None:
                raise self.auth_users_select_raises
            user_id = (params or {}).get("user_id") if isinstance(params, dict) else None
            email = self.auth_users_emails.get(str(user_id)) if user_id is not None else None
            if email is None:
                return FakeResult(rows=[])
            return FakeResult(rows=[(email,)])

        # UPDATE clients SET auth_user_id = ... (JIT backfill write).
        if sql_lower.startswith("update clients") and "auth_user_id" in sql_lower:
            self.auth_update_count += 1
            return FakeResult(rows=[])

        # Raw text() INSERT ... ON CONFLICT DO NOTHING into public.profiles.
        # Records the attempted user_id and simulates ON CONFLICT semantics
        # against the in-memory ``profiles_existing_roles`` map.
        if (
            sql_lower.startswith("insert into public.profiles")
            and "on conflict" in sql_lower
        ):
            user_id = (params or {}).get("user_id") if isinstance(params, dict) else None
            user_id_str = str(user_id) if user_id is not None else ""
            self.profile_upsert_calls.append(user_id_str)
            if user_id_str and user_id_str not in self.profiles_existing_roles:
                # First write for this user — insert with role='client'.
                self.profiles_existing_roles[user_id_str] = "client"
            # else: ON CONFLICT DO NOTHING — existing role preserved.
            return FakeResult(rows=[])

        # FOR UPDATE row lock on agent_sessions.
        if "for update" in sql_lower and "agent_sessions" in sql_lower:
            return FakeResult(
                rows=[self.agent_session.id] if self.agent_session else []
            )

        # max(turn_index) aggregate.
        if "max" in sql_lower and "turn_index" in sql_lower:
            if not self.turns:
                return FakeResult(rows=[None])
            return FakeResult(rows=[max(t.turn_index for t in self.turns)])

        # Join on agent_session + client + voodoo_doll (context load).
        if (
            "agent_sessions" in sql_lower
            and "clients" in sql_lower
            and "voodoo_dolls" in sql_lower
        ):
            if (
                self.agent_session is None
                or self.client_row is None
                or self.doll is None
            ):
                return FakeResult(rows=[])
            return FakeResult(
                rows=[(self.agent_session, self.client_row, self.doll)]
            )

        # Plain agent_sessions lookup (open_or_reuse_session).
        if "agent_sessions" in sql_lower and "ended_at is null" in sql_lower:
            if self.open_agent_session_on_reuse is not None:
                return FakeResult(rows=[self.open_agent_session_on_reuse])
            return FakeResult(rows=[])

        # S07 T03 — itinerary-by-client (ensure-one-per-client helper).
        if (
            "itineraries" in sql_lower
            and "itineraries.client_id" in sql_lower
        ):
            bound = {}
            try:
                bound = dict(stmt.compile().params)
            except Exception:
                bound = {}
            client_id = bound.get("client_id_1")
            match = next(
                (it for it in self.itineraries if str(it.client_id) == str(client_id)),
                None,
            )
            if match is None:
                return FakeResult(rows=[])
            return FakeResult(rows=[match.id])

        # S07 T03 — itinerary-by-id (add_node exists-check).
        if "itineraries" in sql_lower and "itineraries.id" in sql_lower:
            bound = {}
            try:
                bound = dict(stmt.compile().params)
            except Exception:
                bound = {}
            itinerary_id = bound.get("id_1")
            match = next(
                (it for it in self.itineraries if str(it.id) == str(itinerary_id)),
                None,
            )
            if match is None:
                return FakeResult(rows=[])
            return FakeResult(rows=[match.id])

        # Plain clients lookup.
        if "clients" in sql_lower and "agent_sessions" not in sql_lower:
            return FakeResult(
                rows=[self.client_row] if self.client_row else []
            )

        return FakeResult(rows=[])


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def advisor_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def client_row(advisor_id: uuid.UUID, user_id: uuid.UUID) -> Client:
    c = Client(
        owner_id=advisor_id,
        full_name="Serena Wolfe",
        email="serena@example.com",
    )
    c.id = uuid.uuid4()
    c.auth_user_id = user_id
    return c


@pytest.fixture
def voodoo_doll(client_row: Client) -> VoodooDoll:
    doll = VoodooDoll(
        client_id=client_row.id,
        authored_by=client_row.owner_id,
        contact_preference=ContactChannel.email,
        group_type=GroupType.couple,
        children_ages=[],
        travel_party_notes="prefers quiet lodges",
        estimated_net_worth_usd=SECRET_NETWORTH,
        passions=[{"label": "skiing"}],
        motivations={"driver": "status"},
        travel_history=[],
        triggers=[],
        constraints=[],
        deal_breakers=[],
        dream_trip_signals={},
        osint_notes={"redflag": SECRET_OSINT},
    )
    doll.id = uuid.uuid4()
    return doll


@pytest.fixture
def agent_session(client_row: Client) -> AgentSession:
    s = AgentSession(
        client_id=client_row.id,
        agentcore_session_id="runtime-session-xyz",
    )
    s.id = uuid.uuid4()
    return s


@pytest.fixture
def factory(
    client_row: Client,
    voodoo_doll: VoodooDoll,
    agent_session: AgentSession,
) -> FakeFactory:
    return FakeFactory(
        agent_session=agent_session,
        client_row=client_row,
        doll=voodoo_doll,
    )


@pytest.fixture
def advisor_actor(advisor_id: uuid.UUID) -> ActorContext:
    return ActorContext(
        user_id=advisor_id, actor_kind="advisor", actor_id=str(advisor_id)
    )


@pytest.fixture
def user_actor(user_id: uuid.UUID) -> ActorContext:
    return ActorContext(
        user_id=user_id, actor_kind="user", actor_id=str(user_id)
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bedrock_agentcore_runtime_arn=(
            "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/foo-ab123xyz"
        ),
        bedrock_agentcore_memory_id="",
        agent_first_token_timeout_seconds=8.0,
        agent_max_retries=1,
    )


async def _collect(
    stream: AsyncIterator[bytes],
) -> list[bytes]:
    out: list[bytes] = []
    async for chunk in stream:
        out.append(chunk)
    return out


# ── Tests ──────────────────────────────────────────────────────────────────


async def test_stream_turn_happy_path_yields_frames_and_writes_two_turns(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "Hel"},
            {"type": "delta", "text": "lo"},
            {"type": "delta", "text": "!"},
            {"type": "done"},
        ]
    )

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Tell me about Aspen.",
            settings=settings,
        )
    )

    joined = b"".join(frames)
    # first_token frame before the first delta.
    assert b'"type":"first_token"' in joined
    # Three delta payloads make it into SSE frames.
    assert joined.count(b'"type":"delta"') == 3
    # Terminal done frame carries turn_id + latency_ms.
    assert b'"type":"done"' in joined
    assert re.search(rb'"turn_id":"[0-9a-f-]{36}"', joined)

    # Two separate sessions used (one per transaction).
    assert len(factory.sessions_created) == 2

    # Two turn rows: user first, assistant second.
    turn_rows = [row for row in factory.turns if isinstance(row, AgentTurn)]
    assert len(turn_rows) == 2
    user_turn, assistant_turn = turn_rows
    assert user_turn.role is TurnRole.user
    assert user_turn.content == "Tell me about Aspen."
    assert user_turn.actor_kind == "advisor"
    assert user_turn.retried == 0
    assert assistant_turn.role is TurnRole.assistant
    assert assistant_turn.content == "Hello!"
    assert assistant_turn.retried == 0
    assert assistant_turn.first_token_ms is not None
    assert assistant_turn.model == "ab123xyz"


async def test_stream_turn_retries_once_on_upstream_error_before_first_byte(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """First call raises throttling → one retry succeeds → assistant.retried=1."""
    runtime = MockAgentRuntimeClient(
        [
            [],  # first call never yields (exception before any event)
            [
                {"type": "delta", "text": "ok"},
                {"type": "done"},
            ],
        ],
        raise_on_invoke=[AgentRuntimeError(reason="ThrottlingException"), None],
    )

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Ping.",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    assert b'"type":"delta","text":"ok"' in joined
    assert b'"type":"done"' in joined
    # Fallback must NOT have fired.
    assert b'"type":"error"' not in joined

    turns = [r for r in factory.turns if isinstance(r, AgentTurn)]
    assistant = next(t for t in turns if t.role is TurnRole.assistant)
    assert assistant.retried == 1
    assert assistant.content == "ok"
    assert assistant.error_reason is None


async def test_stream_turn_emits_fallback_when_retries_exhausted(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """Both attempts raise → crafted fallback + role='error' + error_reason."""
    runtime = MockAgentRuntimeClient(
        [[], []],
        raise_on_invoke=[
            AgentRuntimeError(reason="ServiceUnavailableException"),
            AgentRuntimeError(reason="ServiceUnavailableException"),
        ],
    )

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Hello?",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    assert b'data: {"type":"error","reason":"upstream_unavailable"}\n\n' in joined
    assert b'"type":"done"' in joined

    turns = [r for r in factory.turns if isinstance(r, AgentTurn)]
    error_row = next(t for t in turns if t.role is TurnRole.error)
    assert error_row.error_reason == "upstream_unavailable"
    assert error_row.content == ""
    assert error_row.retried == 1
    assert error_row.first_token_ms is None


async def test_stream_turn_rejects_advisor_who_does_not_own_client(
    factory: FakeFactory,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """Non-owner advisor → fallback frame + done + NO turn rows written."""
    stranger = ActorContext(
        user_id=uuid.uuid4(), actor_kind="advisor", actor_id="stranger"
    )
    runtime = MockAgentRuntimeClient([{"type": "done"}])

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=stranger,
            session_id=agent_session.id,
            content="poke",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    assert b'"type":"error"' in joined
    # The runtime must never have been invoked.
    assert runtime.calls == []
    # No AgentTurn rows were added.
    assert [r for r in factory.turns if isinstance(r, AgentTurn)] == []


async def test_stream_turn_first_token_timeout_fires_fallback(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """If first-token never arrives within the deadline, fallback fires."""
    tight = Settings(
        bedrock_agentcore_runtime_arn=settings.bedrock_agentcore_runtime_arn,
        agent_first_token_timeout_seconds=0.1,
        agent_max_retries=0,
    )

    async def slow_stream() -> AsyncIterator[dict]:
        import anyio as _anyio

        await _anyio.sleep(0.3)
        yield {"type": "delta", "text": "late"}
        yield {"type": "done"}

    class SlowRuntime:
        calls: list[dict] = []

        def invoke_stream(
            self, *, agentcore_session_id: str, payload: dict
        ) -> AsyncIterator[dict]:
            self.calls.append(
                {
                    "agentcore_session_id": agentcore_session_id,
                    "payload": payload,
                }
            )
            return slow_stream()

        async def create_event(self, **_: Any) -> None:
            return None

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            SlowRuntime(),
            actor=advisor_actor,
            session_id=agent_session.id,
            content="hi",
            settings=tight,
        )
    )
    joined = b"".join(frames)
    assert b'"type":"error","reason":"upstream_unavailable"' in joined
    # Assistant row recorded fallback.
    turns = [r for r in factory.turns if isinstance(r, AgentTurn)]
    error_row = next(t for t in turns if t.role is TurnRole.error)
    assert error_row.error_reason == "upstream_unavailable"


async def test_stream_turn_memory_write_failure_does_not_fail_turn(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CreateEvent failure logs WARN + turn completes normally."""
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "ok"},
            {"type": "done"},
        ]
    )
    runtime.create_event_raises = RuntimeError("kaboom")
    mem_settings = Settings(
        bedrock_agentcore_runtime_arn=(
            "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/foo-ab123xyz"
        ),
        bedrock_agentcore_memory_id="mem-abc",
        agent_first_token_timeout_seconds=8.0,
        agent_max_retries=1,
    )

    caplog.set_level(logging.WARNING, logger="ov_black.agent.service")
    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="hello",
            settings=mem_settings,
        )
    )
    joined = b"".join(frames)
    assert b'"type":"done"' in joined

    # Assistant row still written.
    turns = [r for r in factory.turns if isinstance(r, AgentTurn)]
    assistant = next(t for t in turns if t.role is TurnRole.assistant)
    assert assistant.content == "ok"

    # WARN log emitted with stable event name.
    assert any(
        rec.message == "agent.memory.create_event.failed"
        for rec in caplog.records
    )


async def test_open_or_reuse_session_returns_existing_open_session(
    factory: FakeFactory,
    client_row: Client,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
) -> None:
    """If a session with ended_at IS NULL exists, reuse — don't INSERT."""
    factory.open_agent_session_on_reuse = agent_session
    outcome, session_row, itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=advisor_actor,
        client_id=client_row.id,
    )
    assert outcome is SessionOutcome.OK
    assert session_row is agent_session
    # S07 T05: open_or_reuse_session now ensures a one-per-client itinerary
    # and returns its id so the RSC chat page can hydrate the MoodBoard.
    assert itinerary_id is not None
    # No new AgentSession was added to any FakeSession.
    assert all(
        not isinstance(obj, AgentSession)
        for s in factory.sessions_created
        for obj in s.added
    )


async def test_open_or_reuse_session_inserts_when_none_exists(
    factory: FakeFactory,
    client_row: Client,
    advisor_actor: ActorContext,
) -> None:
    """With no open session, a fresh row is inserted and returned."""
    factory.open_agent_session_on_reuse = None
    outcome, session_row, itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=advisor_actor,
        client_id=client_row.id,
    )
    assert outcome is SessionOutcome.OK
    assert isinstance(session_row, AgentSession)
    # The inserted row uses a real UUID for agentcore_session_id.
    uuid.UUID(session_row.agentcore_session_id)
    # And an itinerary was ensured for the client at session-open time.
    assert itinerary_id is not None
    assert any(str(it.id) == str(itinerary_id) for it in factory.itineraries)


async def test_stream_turn_turn_index_monotonically_increases(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """Two consecutive turns → second user turn gets turn_index 2."""
    runtime = MockAgentRuntimeClient(
        [{"type": "delta", "text": "a"}, {"type": "done"}]
    )

    await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="first",
            settings=settings,
        )
    )
    # Rebuild a fresh runtime — the mock exhausts its script per invocation
    # sequence, but invoke_stream is stateless beyond self.calls.
    runtime2 = MockAgentRuntimeClient(
        [{"type": "delta", "text": "b"}, {"type": "done"}]
    )
    await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime2,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="second",
            settings=settings,
        )
    )

    turns = [r for r in factory.turns if isinstance(r, AgentTurn)]
    # turn 0 user / turn 1 assistant / turn 2 user / turn 3 assistant
    assert [t.turn_index for t in turns] == [0, 1, 2, 3]
    assert [t.role for t in turns] == [
        TurnRole.user,
        TurnRole.assistant,
        TurnRole.user,
        TurnRole.assistant,
    ]


async def test_stream_turn_redaction_sweep_blocks_secret_leaks(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Net-worth and OSINT secrets must NEVER appear in any caplog record.

    Exercises the whole turn loop with every field populated, then walks
    every caplog record at DEBUG level and above and asserts neither the
    net-worth integer nor the OSINT marker string leaks into any log
    message or the repr() of any log attribute.
    """
    caplog.set_level(logging.DEBUG)
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "Hi!"},
            {"type": "done"},
        ]
    )
    await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Please keep this private.",
            settings=settings,
        )
    )

    needles = (str(SECRET_NETWORTH), SECRET_OSINT, "Please keep this private")
    for record in caplog.records:
        msg = record.getMessage()
        for needle in needles:
            assert needle not in msg, (
                f"secret {needle!r} leaked into log message: {msg!r}"
            )
        for attr_name, attr_val in record.__dict__.items():
            if attr_name in ("msg", "args"):
                continue
            rendered = repr(attr_val)
            for needle in needles:
                assert needle not in rendered, (
                    f"secret {needle!r} leaked via record.{attr_name} = {rendered!r}"
                )


# ── JIT auth_user_id backfill (T01) ────────────────────────────────────────


async def test_open_or_reuse_session_jit_backfill_matching_email_populates_auth_user_id(
    factory: FakeFactory,
    client_row: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NULL auth_user_id + matching auth.users email → backfills + OK + log."""
    # Freshly-magic-linked client: no link established yet.
    client_row.auth_user_id = None
    caller_user_id = uuid.uuid4()
    # Simulate Supabase auth.users returning the same email (different case
    # is fine — match is case-insensitive).
    factory.auth_users_emails[str(caller_user_id)] = client_row.email.upper()
    factory.open_agent_session_on_reuse = None

    user_actor = ActorContext(
        user_id=caller_user_id, actor_kind="user", actor_id=str(caller_user_id)
    )

    caplog.set_level(logging.INFO, logger="ov_black.agent.service")
    outcome, session_row, _itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=user_actor,
        client_id=client_row.id,
    )

    assert outcome is SessionOutcome.OK
    assert isinstance(session_row, AgentSession)
    # The backfill updated both the DB (one UPDATE) and the in-memory row.
    assert factory.auth_update_count == 1
    assert client_row.auth_user_id == caller_user_id

    # Exactly one backfill log event, carrying session_id + client_id +
    # user_id and nothing else from the sensitive set (no email, no name).
    backfill_records = [
        rec for rec in caplog.records
        if rec.message == "agent.auth.client_backfilled"
    ]
    assert len(backfill_records) == 1
    rec = backfill_records[0]
    assert getattr(rec, "session_id") == str(session_row.id)
    assert getattr(rec, "client_id") == str(client_row.id)
    assert getattr(rec, "user_id") == str(caller_user_id)
    # Email MUST NEVER land on this record (redaction constraint).
    for attr_name, attr_val in rec.__dict__.items():
        assert client_row.email not in repr(attr_val), (
            f"email leaked via record.{attr_name}"
        )


async def test_open_or_reuse_session_jit_backfill_mismatched_email_forbidden(
    factory: FakeFactory,
    client_row: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NULL auth_user_id + mismatched auth.users email → FORBIDDEN, no UPDATE, no log."""
    client_row.auth_user_id = None
    caller_user_id = uuid.uuid4()
    # Different email → must NOT backfill.
    factory.auth_users_emails[str(caller_user_id)] = "someone.else@example.com"
    factory.open_agent_session_on_reuse = None

    user_actor = ActorContext(
        user_id=caller_user_id, actor_kind="user", actor_id=str(caller_user_id)
    )

    caplog.set_level(logging.INFO, logger="ov_black.agent.service")
    outcome, session_row, itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=user_actor,
        client_id=client_row.id,
    )

    assert outcome is SessionOutcome.FORBIDDEN
    assert session_row is None
    # Non-OK outcomes must not leak an itinerary id (D015 collapse shape).
    assert itinerary_id is None
    # No UPDATE was issued, and the in-memory row is still NULL.
    assert factory.auth_update_count == 0
    assert client_row.auth_user_id is None
    # No backfill log was emitted.
    assert not any(
        rec.message == "agent.auth.client_backfilled" for rec in caplog.records
    )


async def test_open_or_reuse_session_jit_backfill_skipped_when_already_populated(
    factory: FakeFactory,
    client_row: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Already-populated auth_user_id → no UPDATE issued + no backfill log."""
    # auth_user_id is already the caller's id (the fixture sets this) — this
    # is the steady-state path for a client who has already had one session.
    assert client_row.auth_user_id is not None
    caller_user_id = client_row.auth_user_id
    factory.open_agent_session_on_reuse = None

    user_actor = ActorContext(
        user_id=caller_user_id, actor_kind="user", actor_id=str(caller_user_id)
    )

    caplog.set_level(logging.INFO, logger="ov_black.agent.service")
    outcome, session_row, _itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=user_actor,
        client_id=client_row.id,
    )

    assert outcome is SessionOutcome.OK
    assert isinstance(session_row, AgentSession)
    # No UPDATE — already populated means the backfill path is never entered.
    assert factory.auth_update_count == 0
    # And no backfill log event.
    assert not any(
        rec.message == "agent.auth.client_backfilled" for rec in caplog.records
    )


# ── JIT profiles upsert (T02) ──────────────────────────────────────────────


async def test_open_or_reuse_session_jit_backfill_profiles_upsert_inserts_client_role(
    factory: FakeFactory,
    client_row: Client,
) -> None:
    """First-ever JIT backfill for a user → profiles INSERT with role='client'.

    Locks in T02's contract: the same backfill transaction that sets
    clients.auth_user_id ALSO writes a public.profiles row (id=user_id,
    role='client') with ON CONFLICT DO NOTHING so the auth grid stays
    self-consistent on the very next request.
    """
    client_row.auth_user_id = None
    caller_user_id = uuid.uuid4()
    factory.auth_users_emails[str(caller_user_id)] = client_row.email
    factory.open_agent_session_on_reuse = None
    # No pre-existing profiles row for this user — expect INSERT path.
    assert str(caller_user_id) not in factory.profiles_existing_roles

    user_actor = ActorContext(
        user_id=caller_user_id, actor_kind="user", actor_id=str(caller_user_id)
    )

    outcome, session_row, _itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=user_actor,
        client_id=client_row.id,
    )

    assert outcome is SessionOutcome.OK
    assert isinstance(session_row, AgentSession)
    # Exactly one profiles INSERT ... ON CONFLICT was issued, for the caller.
    assert factory.profile_upsert_calls == [str(caller_user_id)]
    # The simulated ON CONFLICT semantics wrote role='client' (no pre-existing
    # row existed for this user).
    assert factory.profiles_existing_roles[str(caller_user_id)] == "client"
    # And the clients UPDATE also fired — both writes share the same txn.
    assert factory.auth_update_count == 1


async def test_open_or_reuse_session_jit_backfill_profiles_upsert_never_downgrades_advisor(
    factory: FakeFactory,
    client_row: Client,
) -> None:
    """Existing profiles row with role='advisor' must NEVER be downgraded.

    ON CONFLICT DO NOTHING makes this structurally impossible: if the test's
    in-memory ``profiles_existing_roles`` already carries the caller's user_id
    mapped to 'advisor', the INSERT is a no-op and the role is preserved.
    This test locks the contract against a future regression where someone
    flips the statement to ON CONFLICT (id) DO UPDATE or similar.
    """
    client_row.auth_user_id = None
    caller_user_id = uuid.uuid4()
    factory.auth_users_emails[str(caller_user_id)] = client_row.email
    factory.open_agent_session_on_reuse = None
    # Pre-existing advisor profile row — must remain advisor after the call.
    factory.profiles_existing_roles[str(caller_user_id)] = "advisor"

    user_actor = ActorContext(
        user_id=caller_user_id, actor_kind="user", actor_id=str(caller_user_id)
    )

    outcome, session_row, _itinerary_id = await open_or_reuse_session(
        factory,  # type: ignore[arg-type]
        actor=user_actor,
        client_id=client_row.id,
    )

    assert outcome is SessionOutcome.OK
    assert isinstance(session_row, AgentSession)
    # The INSERT statement was still issued (ON CONFLICT handles the rest).
    assert factory.profile_upsert_calls == [str(caller_user_id)]
    # The critical invariant: role='advisor' is preserved.
    assert factory.profiles_existing_roles[str(caller_user_id)] == "advisor"


# ── S07 card-proposal protocol (T02) ───────────────────────────────────────


def test_system_prompt_includes_card_protocol() -> None:
    """The assembled system prompt teaches the model the card event shape."""
    prompt = build_system_prompt("CONTEXT_PLACEHOLDER")
    # Exact protocol literal — the model must learn the raw JSON shape.
    assert '"type": "card"' in prompt
    # The protocol names source_id as the OV inventory reference.
    assert "source_id" in prompt
    # And it tells the model the frame carries source='ov'.
    assert '"source": "ov"' in prompt


async def test_card_event_passes_through(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """A ``card`` event from the runtime round-trips to the client.

    Locks in the S07 contract that the service forwards the frame with the
    snapshot intact; T03 additionally augments the outbound frame with a
    ``node_id`` (the persisted experience-node id) so the client reducer can
    key its state on a stable identifier.
    """
    card_event = {
        "type": "card",
        "source": "ov",
        "source_id": "ov-123",
        "snapshot": {
            "title": "Heli-ski the Chugach",
            "cover_image": "https://cdn.ov.test/chugach.jpg",
            "price": "USD 48000",
            "duration_days": 7,
            "difficulty": "expert",
            "location": "Valdez, Alaska",
            "activities": ["heli-ski", "lodge"],
        },
    }
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "Here's one."},
            card_event,
            {"type": "done"},
        ]
    )

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Suggest something wild.",
            settings=settings,
        )
    )
    joined = b"".join(frames)

    # Pull each `data: ...` line, parse it, and find the card frame.
    data_lines = [
        line[len(b"data: "):]
        for line in joined.split(b"\n")
        if line.startswith(b"data: ")
    ]
    cards = [
        json.loads(line.decode("utf-8"))
        for line in data_lines
        if b'"type":"card"' in line
    ]
    assert len(cards) == 1
    forwarded = cards[0]
    # Snapshot dict survives byte-for-byte — no re-keying, no stripping.
    assert forwarded["type"] == "card"
    assert forwarded["source"] == card_event["source"]
    assert forwarded["source_id"] == card_event["source_id"]
    assert forwarded["snapshot"] == card_event["snapshot"]
    assert forwarded["snapshot"]["activities"] == ["heli-ski", "lodge"]
    # T03: forwarded frame now carries node_id — uuid-string on success,
    # None on persist failure. The fake factory persists cleanly here.
    assert forwarded["node_id"] is not None
    uuid.UUID(forwarded["node_id"])  # round-trips as a uuid string


async def test_card_frame_persists_as_proposed_node(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """Card frames land as ``nodes`` rows with status=proposed BEFORE forward.

    T03 durability half: even if the client closes the tab mid-stream, the
    proposed card must survive for a reload hydration.
    """
    card_event = {
        "type": "card",
        "source": "ov",
        "source_id": "ov-42",
        "snapshot": {
            "title": "Sahara glamping",
            "cover_image": "https://cdn.ov.test/sahara.jpg",
            "activities": ["camel", "stargaze"],
        },
    }
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "I've got one."},
            card_event,
            {"type": "done"},
        ]
    )

    await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Suggest something wild.",
            settings=settings,
        )
    )

    # Exactly one Node was persisted with the proposed-experience shape.
    assert len(factory.nodes) == 1
    node = factory.nodes[0]
    assert node.type == NodeType.experience
    assert node.status == NodeStatus.proposed
    assert node.source == "ov"
    assert node.source_id == "ov-42"
    assert node.title == "Sahara glamping"
    assert node.metadata_ == {"snapshot": card_event["snapshot"]}

    # A matching node_history row was written with actor_kind='agent'.
    assert len(factory.node_histories) == 1
    history = factory.node_histories[0]
    assert history.node_id == node.id
    assert history.op == "insert"
    assert history.actor_kind == itineraries_service.ActorKind.AGENT.value
    assert history.actor_id == agent_session.agentcore_session_id

    # And an itinerary was auto-created with title='Concierge draft'.
    assert len(factory.itineraries) == 1
    itinerary = factory.itineraries[0]
    assert itinerary.client_id == agent_session.client_id
    assert itinerary.title == "Concierge draft"
    assert node.itinerary_id == itinerary.id


async def test_card_frame_reuses_existing_itinerary(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
) -> None:
    """Two cards in one turn land under the same itinerary row.

    Guards against the duplicate-itinerary-row bug where a naive
    implementation would INSERT a new itinerary per card.
    """
    # Pre-seed an itinerary for this client.
    existing = Itinerary(
        client_id=agent_session.client_id,
        title="pre-existing",
    )
    existing.id = uuid.uuid4()
    factory.itineraries.append(existing)

    card_a = {
        "type": "card",
        "source": "ov",
        "source_id": "ov-1",
        "snapshot": {"title": "A", "activities": []},
    }
    card_b = {
        "type": "card",
        "source": "ov",
        "source_id": "ov-2",
        "snapshot": {"title": "B", "activities": []},
    }
    runtime = MockAgentRuntimeClient(
        [
            card_a,
            card_b,
            {"type": "done"},
        ]
    )

    await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Pitch me two.",
            settings=settings,
        )
    )

    # No new itinerary was created — both nodes land under the existing one.
    assert len(factory.itineraries) == 1
    assert len(factory.nodes) == 2
    assert factory.nodes[0].itinerary_id == existing.id
    assert factory.nodes[1].itinerary_id == existing.id


async def test_card_frame_persist_failure_is_non_fatal(
    factory: FakeFactory,
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If ``add_node`` fails, the stream continues and a WARNING is logged.

    Persistence failures MUST NOT block the stream — the frame still goes
    to the browser and the subsequent ``done`` frame still reaches the
    client. Reload hydration just won't see the lost card.
    """
    async def _failing_add_node(
        session: Any,
        actor: Any,
        **kwargs: Any,
    ) -> itineraries_service.ItineraryError:
        return itineraries_service.ItineraryError(
            outcome=itineraries_service.ItineraryOutcome.NOT_FOUND,
            detail=None,
        )

    monkeypatch.setattr(
        "app.services.agent.itineraries_service.add_node",
        _failing_add_node,
    )

    card_event = {
        "type": "card",
        "source": "ov",
        "source_id": "ov-doom",
        "snapshot": {"title": "X", "activities": []},
    }
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "Try this."},
            card_event,
            {"type": "done"},
        ]
    )

    caplog.set_level(logging.WARNING, logger="ov_black.agent.service")
    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Anything?",
            settings=settings,
        )
    )
    joined = b"".join(frames)

    # The terminal ``done`` frame reaches the client — stream wasn't killed.
    assert b'"type":"done"' in joined

    # The forwarded card frame carries node_id=None because persist failed.
    data_lines = [
        line[len(b"data: "):]
        for line in joined.split(b"\n")
        if line.startswith(b"data: ")
    ]
    cards = [
        json.loads(line.decode("utf-8"))
        for line in data_lines
        if b'"type":"card"' in line
    ]
    assert len(cards) == 1
    assert cards[0]["node_id"] is None

    # WARNING was emitted with the persist_failed event + carries no snapshot.
    warns = [
        r for r in caplog.records
        if r.name == "ov_black.agent.service"
        and r.levelno == logging.WARNING
        and r.getMessage() == "agent.card.persist_failed"
    ]
    assert len(warns) == 1
    record = warns[0]
    # Required stable fields present.
    assert getattr(record, "session_id", None) == str(agent_session.id)
    assert getattr(record, "source", None) == "ov"
    assert getattr(record, "source_id", None) == "ov-doom"
    assert getattr(record, "reason", None) == "not_found"
    # No snapshot / description / photo leaked into the log record.
    record_blob = json.dumps(record.__dict__, default=str)
    assert "snapshot" not in record_blob
    assert card_event["snapshot"]["title"] not in record_blob
