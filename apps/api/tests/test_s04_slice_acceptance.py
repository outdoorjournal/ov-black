"""S04 slice acceptance — one test per bullet of the slice demo.

Each test exercises the real HTTP surface end-to-end against a locally
running Supabase Postgres, with the ``get_agent_runtime`` dependency
overridden to a scripted ``MockAgentRuntimeClient`` so the suite is
hermetic against the live Bedrock AgentCore runtime.

Skipped automatically (not failed) on a fresh checkout where Supabase is
not running, mirroring the ``_supabase_running()`` pattern in
``tests/test_s02_slice_acceptance.py``.

The six tests map to the slice demo bullets:

1. Seeded Voodoo Doll loads into the first turn's system prompt.
2. A scripted 5-turn onboarding persists all 10 turns and keeps the
   runtimeSessionId stable across every call.
3. ``first_token_ms`` lands in both the SSE frame and the DB row.
4. A ThrottlingException on turn 3 silently retries without any SSE
   frame loss.
5. Exhausted retries surface the crafted fallback frame + error row.
6. Voodoo Doll sensitive context never appears in any log record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from app.agent.bedrock import AgentRuntimeError, MockAgentRuntimeClient
from app.db import get_session
from app.main import app as fastapi_app
from app.routers import agent as agent_router_module
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


pytestmark = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


# ── DB-side helpers (run via asyncio.run() so each gets a fresh loop) ──────


def _run_with_engine(coro_fn) -> Any:
    """Invoke an async fn that takes (engine,) on a fresh loop.

    Every call gets its own loop, its own engine, and the engine is
    disposed before the loop closes — matches the cross-loop-safe helper
    from ``tests/test_s02_slice_acceptance.py``.
    """

    async def _go() -> Any:
        eng = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            return await coro_fn(eng)
        finally:
            await eng.dispose()

    return asyncio.run(_go())


async def _insert_auth_user(conn: Any, user_id: uuid.UUID, email: str) -> None:
    """Create a minimal auth.users row so FK-backed inserts succeed."""
    await conn.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": user_id, "email": email},
    )


@dataclass
class Seed:
    """Identities produced by ``_seed_fixture`` for a single test run."""

    advisor_id: uuid.UUID
    client_id: uuid.UUID


def _seed_advisor_client_dossier(
    *,
    passions: list,
    estimated_net_worth_usd: int | None = None,
    osint_notes: dict | None = None,
) -> Seed:
    """Seed one advisor + profile + client + dossier (+ dossier/osint facts).

    Returns the generated advisor_id + client_id. Passions become
    ``dossier_facts`` rows with ``kind=passion``; ``osint_notes`` keys
    each become an ``osint_facts`` row. Callers are responsible for
    calling ``_cleanup_seed`` with the advisor_id once the test is done.
    """
    advisor_id = uuid.uuid4()
    client_id = uuid.uuid4()
    advisor_email = f"advisor-{advisor_id.hex[:8]}@s04.example.com"
    client_email = f"client-{client_id.hex[:8]}@s04.example.com"

    async def _do(eng) -> None:
        async with eng.begin() as conn:
            await _insert_auth_user(conn, advisor_id, advisor_email)
            await _insert_auth_user(conn, client_id, client_email)
            await conn.execute(
                text("insert into public.profiles (id, role) values (:id, 'advisor')"),
                {"id": advisor_id},
            )
            await conn.execute(
                text(
                    """
                    insert into public.clients (id, owner_id, full_name, email)
                    values (:id, :owner, :name, :email)
                    """
                ),
                {
                    "id": client_id,
                    "owner": advisor_id,
                    "name": "Serena Wolfe",
                    "email": client_email,
                },
            )
            await conn.execute(
                text(
                    """
                    insert into public.dossiers (
                      client_id, authored_by, contact_preference,
                      estimated_net_worth_usd
                    ) values (
                      :client_id, :authored_by, 'email', :net_worth
                    )
                    """
                ),
                {
                    "client_id": client_id,
                    "authored_by": advisor_id,
                    "net_worth": estimated_net_worth_usd,
                },
            )
            for passion_label in passions:
                await conn.execute(
                    text(
                        """
                        insert into public.dossier_facts
                          (client_id, kind, text, source_kind, recorded_by)
                        values
                          (:client_id, 'passion', :text, 'advisor', :recorded_by)
                        """
                    ),
                    {
                        "client_id": client_id,
                        "text": passion_label,
                        "recorded_by": advisor_id,
                    },
                )
            for key, value in (osint_notes or {}).items():
                kind = (
                    key
                    if key
                    in ("linkedin", "facebook", "instagram", "press", "company", "public_record")
                    else "other"
                )
                await conn.execute(
                    text(
                        """
                        insert into public.osint_facts
                          (client_id, kind, text, source_kind, recorded_by, source_ref)
                        values
                          (:client_id, :kind, :text, 'advisor', :recorded_by,
                           cast(:source_ref as jsonb))
                        """
                    ),
                    {
                        "client_id": client_id,
                        "kind": kind,
                        "text": value if isinstance(value, str) else json.dumps(value),
                        "recorded_by": advisor_id,
                        "source_ref": json.dumps({"key": key}),
                    },
                )

    _run_with_engine(_do)
    return Seed(advisor_id=advisor_id, client_id=client_id)


def _cleanup_seed(advisor_id: uuid.UUID, client_id: uuid.UUID | None = None) -> None:
    """Delete any agent state + the seeded identities. ON DELETE CASCADE
    handles public.dossiers + per-fact tables and public.agent_sessions/turns.

    S07 T05: ``client_id`` is optional to keep backward compatibility with
    existing callers; when provided, the matching auth.users row seeded for
    the client is also deleted (itineraries.client_id cascades via SET NULL,
    which is fine — the S04 tests don't inspect the post-cleanup state).
    """

    async def _do(eng) -> None:
        async with eng.begin() as conn:
            # auth.users cascade → clients cascade → dossiers + per-fact
            # tables, agent_sessions, agent_turns. Profile also cascades.
            await conn.execute(
                text("delete from public.profiles where id = :id"),
                {"id": advisor_id},
            )
            await conn.execute(
                text("delete from auth.users where id = :id"),
                {"id": advisor_id},
            )
            if client_id is not None:
                await conn.execute(
                    text("delete from auth.users where id = :id"),
                    {"id": client_id},
                )

    _run_with_engine(_do)


def _fetch_rows(sql: str, **params: Any) -> list[Any]:
    """Run a SELECT and return all rows as tuples on a fresh loop."""

    async def _do(eng) -> list[Any]:
        async with eng.begin() as conn:
            return list((await conn.execute(text(sql), params)).all())

    return _run_with_engine(_do)


# ── Per-request sessionmaker ────────────────────────────────────────────────


def _fresh_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Build a new sessionmaker bound to a fresh engine.

    The S04 service calls ``get_sessionmaker()`` at the router layer and
    passes it down to ``stream_turn`` / ``open_or_reuse_session``. The
    module-level cached sessionmaker binds to whichever loop first
    touched it — that fights TestClient's portal-spawned loop.
    Creating one per router invocation sidesteps the cross-loop problem
    (engines are cheap enough for tests; they leak until GC).
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


# ── App fixtures (runtime override + fresh session + JWT) ──────────────────


class _RuntimeProxy:
    """Delegate every attribute access to the currently-armed runtime.

    The router's ``get_agent_runtime`` reads directly from
    ``app.state.agent_runtime`` rather than going through FastAPI's
    ``Depends`` graph, so ``dependency_overrides`` is a no-op here. We
    install this proxy once and let tests swap the underlying runtime via
    ``slot['runtime']`` on each pre-arm.
    """

    def __init__(self, slot: dict[str, Any]) -> None:
        self._slot = slot

    def _target(self) -> Any:
        target = self._slot["runtime"]
        if target is None:
            raise AssertionError("test did not arm a MockAgentRuntimeClient before POSTing")
        return target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)


@pytest.fixture()
def runtime_slot() -> Iterator[dict[str, Any]]:
    """A mutable slot tests write a ``MockAgentRuntimeClient`` into.

    The router resolves its runtime via ``app.state.agent_runtime``, so we
    swap in a proxy that forwards attribute access to whichever scripted
    mock the current test wrote into the slot.
    """
    slot: dict[str, Any] = {"runtime": None}
    original = getattr(fastapi_app.state, "agent_runtime", None)
    fastapi_app.state.agent_runtime = _RuntimeProxy(slot)
    try:
        yield slot
    finally:
        fastapi_app.state.agent_runtime = original


@pytest.fixture()
def session_override() -> Iterator[None]:
    """Swap get_session + agent_router_module.get_sessionmaker for fresh ones.

    ``get_session`` yields a per-request AsyncSession on a throwaway engine
    (matches S02). ``get_sessionmaker`` (the module-level attribute the
    router imports) is monkey-patched to return a freshly-built
    sessionmaker each call, so the service's ``async with factory()``
    never touches the cross-loop cached pool.
    """
    original = agent_router_module.get_sessionmaker

    async def _session_dep() -> AsyncIterator[AsyncSession]:
        eng = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        maker = async_sessionmaker(bind=eng, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                yield s
        finally:
            await eng.dispose()

    fastapi_app.dependency_overrides[get_session] = _session_dep
    agent_router_module.get_sessionmaker = _fresh_sessionmaker
    try:
        yield
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        agent_router_module.get_sessionmaker = original


@pytest.fixture()
def client(session_override: None) -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


def _auth_headers(make_token, advisor_id: uuid.UUID) -> dict[str, str]:
    """Mint an advisor JWT whose ``sub`` matches the seeded advisor row.

    The router's ``_actor_for_user`` helper parses ``sub`` as a UUID and
    then looks up ``public.profiles`` — we seed a profile with
    ``role='advisor'`` so the caller lands with ``actor_kind='advisor'``
    and the service's auth check matches on ``clients.owner_id``.
    """
    return {"Authorization": f"Bearer {make_token(sub=str(advisor_id))}"}


# ── SSE helpers ─────────────────────────────────────────────────────────────


def _parse_frames(raw: str) -> list[dict]:
    """Parse the ``data: {...}\\n\\n`` envelope into a list of JSON dicts."""
    frames: list[dict] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or not block.startswith("data:"):
            continue
        body = block[len("data:") :].strip()
        frames.append(json.loads(body))
    return frames


def _happy_script(text_chunk: str) -> list[dict]:
    """A complete one-turn scripted response: one delta + done."""
    return [{"type": "delta", "text": text_chunk}, {"type": "done"}]


def _open_session(
    client: TestClient, headers: dict[str, str], client_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    resp = client.post("/sessions", json={"client_id": str(client_id)}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return uuid.UUID(body["session_id"]), body["agentcore_session_id"]


# ── Test 1: seeded dossier_facts load into the first turn's prompt ─────────


def test_seeded_dossier_facts_load_into_first_turn(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
) -> None:
    """Demo bullet 1: the agent's system prompt is grounded on the dossier."""
    seed = _seed_advisor_client_dossier(passions=["high-altitude walking"])
    headers = _auth_headers(make_token, seed.advisor_id)

    runtime = MockAgentRuntimeClient([_happy_script("Hi.")])
    runtime_slot["runtime"] = runtime

    try:
        session_id, _ac_id = _open_session(client, headers, seed.client_id)

        resp = client.post(
            f"/sessions/{session_id}/turn",
            json={"content": "Hello"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        # Drain the stream so the assistant-write transaction commits
        # before we fall through to assertions.
        _ = resp.text

        # The payload the service sent into ``runtime.invoke_stream``
        # carries the assembled system prompt as ``payload['system']``.
        assert runtime.calls, "runtime never invoked"
        payload = runtime.calls[0]["payload"]
        system_prompt = payload.get("system", "")
        assert "high-altitude walking" in system_prompt, (
            "Dossier passion fact did not reach the system prompt"
        )
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Test 2: 5-turn scripted onboarding persists all turns ──────────────────


def test_scripted_five_turn_onboarding_persists_all_turns(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
) -> None:
    """Demo bullet 2: 5 POSTs → 10 rows (5 user + 5 assistant) at indices
    0..9, runtimeSessionId stable across every call."""
    seed = _seed_advisor_client_dossier(passions=["slow travel"])
    headers = _auth_headers(make_token, seed.advisor_id)

    assistant_texts = [
        "First reply.",
        "Second reply.",
        "Third reply.",
        "Fourth reply.",
        "Fifth reply.",
    ]
    runtime = MockAgentRuntimeClient(events=[_happy_script(t) for t in assistant_texts])
    runtime_slot["runtime"] = runtime

    try:
        session_id, ac_id = _open_session(client, headers, seed.client_id)

        user_msgs = [f"Q{i + 1}" for i in range(5)]
        for msg in user_msgs:
            resp = client.post(
                f"/sessions/{session_id}/turn",
                json={"content": msg},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            _ = resp.text  # drain

        # Every invoke carried the SAME runtimeSessionId.
        assert len(runtime.calls) == 5
        ac_ids = {call["agentcore_session_id"] for call in runtime.calls}
        assert ac_ids == {ac_id}, "runtimeSessionId drifted across turns — hybrid state broken"

        # 10 rows, alternating roles, turn_index 0..9.
        rows = _fetch_rows(
            """
            select turn_index, role, content
              from public.agent_turns
             where session_id = :sid
          order by turn_index
            """,
            sid=session_id,
        )
        assert len(rows) == 10
        indices = [r[0] for r in rows]
        roles = [r[1] for r in rows]
        assert indices == list(range(10))
        assert roles == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        # User content matches the POST bodies.
        for i, msg in enumerate(user_msgs):
            assert rows[i * 2][2] == msg
        # Assistant content matches the scripted replies.
        for i, reply in enumerate(assistant_texts):
            assert rows[i * 2 + 1][2] == reply
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Test 3: first_token_ms lands in the SSE frame + the DB row ─────────────


def test_first_token_ms_recorded_under_budget(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
) -> None:
    """Demo bullet 3: R015's measurement surface is wired end-to-end."""
    seed = _seed_advisor_client_dossier(passions=["photography"])
    headers = _auth_headers(make_token, seed.advisor_id)

    # Scripted first_token event declares ms=100; the service also
    # derives its own timing for the log/DB row. Either way the SSE
    # frame and the row should satisfy the R015 <= 2000 ms envelope
    # under unit-test conditions.
    runtime = MockAgentRuntimeClient(
        [
            [
                {"type": "first_token", "ms": 100},
                {"type": "delta", "text": "ok"},
                {"type": "done"},
            ]
        ]
    )
    runtime_slot["runtime"] = runtime

    try:
        session_id, _ac = _open_session(client, headers, seed.client_id)

        resp = client.post(
            f"/sessions/{session_id}/turn",
            json={"content": "When can I see Patagonia?"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        frames = _parse_frames(resp.text)
        first_token_frames = [f for f in frames if f.get("type") == "first_token"]
        assert first_token_frames, "no first_token SSE frame emitted"
        ms = int(first_token_frames[0]["ms"])
        assert 0 <= ms <= 2000, f"first_token ms out of R015 envelope: {ms}"

        rows = _fetch_rows(
            """
            select first_token_ms, role
              from public.agent_turns
             where session_id = :sid and role = 'assistant'
            """,
            sid=session_id,
        )
        assert rows, "no assistant row persisted"
        assert rows[0][0] is not None, "agent_turns.first_token_ms is NULL"
        assert 0 <= int(rows[0][0]) <= 2000
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Test 4: ThrottlingException on turn 3 → silent retry, no frame loss ────


def test_throttling_on_turn_3_triggers_silent_retry_without_frame_loss(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
) -> None:
    """Demo bullet 4: R018 silent-retry is invisible to the caller."""
    seed = _seed_advisor_client_dossier(passions=["polar expeditions"])
    headers = _auth_headers(make_token, seed.advisor_id)

    # Six total invoke_stream calls across the 5 turns: turn 3 retries
    # once, so its attempt-1 slot raises and attempt-2 succeeds.
    # Indexed scripts (call_index → events):
    #   0 turn 1 ok, 1 turn 2 ok, 2 turn 3 attempt 1 (empty, raises),
    #   3 turn 3 attempt 2 ok, 4 turn 4 ok, 5 turn 5 ok.
    scripts = [
        _happy_script("reply 1"),
        _happy_script("reply 2"),
        [],
        _happy_script("reply 3"),
        _happy_script("reply 4"),
        _happy_script("reply 5"),
    ]
    raises: list[BaseException | None] = [
        None,
        None,
        AgentRuntimeError(reason="ThrottlingException"),
        None,
        None,
        None,
    ]
    runtime = MockAgentRuntimeClient(events=scripts, raise_on_invoke=raises)
    runtime_slot["runtime"] = runtime

    try:
        session_id, _ac = _open_session(client, headers, seed.client_id)

        turn_3_body: str | None = None
        for i in range(5):
            resp = client.post(
                f"/sessions/{session_id}/turn",
                json={"content": f"turn {i + 1}"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.text
            if i == 2:
                turn_3_body = body

        # Turn 3's SSE stream must NOT contain an error frame.
        assert turn_3_body is not None
        frames = _parse_frames(turn_3_body)
        kinds = [f.get("type") for f in frames]
        assert "error" not in kinds, "retry should be silent — error frame leaked"
        # And it must include the full delta + done envelope.
        assert "delta" in kinds
        assert "done" in kinds

        # DB-side: turn 3's assistant row is role='assistant' and
        # retried=1. Turn indices are 0/1 (turn 1), 2/3 (turn 2), 4/5
        # (turn 3), so assistant-3 lives at turn_index = 5.
        rows = _fetch_rows(
            """
            select turn_index, role, retried, error_reason
              from public.agent_turns
             where session_id = :sid
          order by turn_index
            """,
            sid=session_id,
        )
        # 5 turns × 2 rows each = 10.
        assert len(rows) == 10
        # Locate the assistant row for turn 3 (turn_index 5).
        asst_3 = next(r for r in rows if r[0] == 5)
        assert asst_3[1] == "assistant"
        assert asst_3[2] == 1, f"retried should be 1, got {asst_3[2]}"
        assert asst_3[3] is None
        # And turns 1/2/4/5 did not retry.
        for idx in (1, 3, 7, 9):
            row = next(r for r in rows if r[0] == idx)
            assert row[2] == 0, f"unexpected retry on turn_index {idx}"
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Test 5: both attempts fail → crafted fallback + error row ──────────────


def test_retries_exhausted_surfaces_crafted_fallback(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
) -> None:
    """Demo bullet 5: R018 crafted-fallback lands when retries exhaust."""
    seed = _seed_advisor_client_dossier(passions=["culinary tours"])
    headers = _auth_headers(make_token, seed.advisor_id)

    runtime = MockAgentRuntimeClient(
        events=[[], []],
        raise_on_invoke=[
            AgentRuntimeError(reason="ThrottlingException"),
            AgentRuntimeError(reason="ThrottlingException"),
        ],
    )
    runtime_slot["runtime"] = runtime

    try:
        session_id, _ac = _open_session(client, headers, seed.client_id)

        resp = client.post(
            f"/sessions/{session_id}/turn",
            json={"content": "Book me a Michelin tour."},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.text

        # SSE stream must carry the crafted fallback frame exactly.
        assert 'data: {"type":"error","reason":"upstream_unavailable"}' in body, body

        # Both attempts were made.
        assert len(runtime.calls) == 2

        # DB row: assistant slot has role='error', error_reason matches,
        # retried=1.
        rows = _fetch_rows(
            """
            select role, error_reason, retried, content
              from public.agent_turns
             where session_id = :sid
          order by turn_index
            """,
            sid=session_id,
        )
        assert len(rows) == 2  # one user, one error
        user_row, error_row = rows
        assert user_row[0] == "user"
        assert error_row[0] == "error"
        assert error_row[1] == "upstream_unavailable"
        assert error_row[2] == 1
        assert error_row[3] == ""
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Test 6: Voodoo Doll sensitive context never appears in logs ────────────


_SENSITIVE_NETWORTH = 1234567
_SENSITIVE_OSINT_TOKEN = "DO_NOT_LOG_ME"


def _record_leaks(record: logging.LogRecord, needle: str) -> bool:
    """Return True if ``needle`` appears anywhere in the record."""
    if needle in record.getMessage():
        return True
    if record.args and needle in str(record.args):
        return True
    for value in record.__dict__.values():
        try:
            if needle in str(value):
                return True
        except Exception:
            continue
    return False


def test_traveler_context_never_appears_in_logs(
    client: TestClient,
    runtime_slot: dict[str, Any],
    make_token,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Demo bullet 6: sensitive context never leaks into any log record."""
    seed = _seed_advisor_client_dossier(
        passions=["off-grid"],
        estimated_net_worth_usd=_SENSITIVE_NETWORTH,
        osint_notes={"private": _SENSITIVE_OSINT_TOKEN},
    )
    headers = _auth_headers(make_token, seed.advisor_id)

    runtime = MockAgentRuntimeClient([_happy_script("Understood.")])
    runtime_slot["runtime"] = runtime

    try:
        caplog.set_level(logging.DEBUG, logger="ov_black")
        session_id, _ac = _open_session(client, headers, seed.client_id)

        resp = client.post(
            f"/sessions/{session_id}/turn",
            json={"content": "Ground me in my preferences."},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        _ = resp.text

        net_worth_str = str(_SENSITIVE_NETWORTH)
        osint_str = _SENSITIVE_OSINT_TOKEN

        for record in caplog.records:
            assert not _record_leaks(record, net_worth_str), (
                "estimated_net_worth_usd leaked into log record: "
                f"{record.name} {record.getMessage()!r}"
            )
            assert not _record_leaks(record, osint_str), (
                f"osint fact text leaked into log record: {record.name} {record.getMessage()!r}"
            )
    finally:
        _cleanup_seed(seed.advisor_id, seed.client_id)


# ── Self-check: regex imports are still referenced ─────────────────────────

_ = re  # silence unused-import linters when the regex helper is trimmed
