"""Bedrock AgentCore runtime client wrapper.

We talk to AgentCore through a narrow Protocol so the service layer can inject
a mock during tests and swap in the real boto3-backed client in production.
boto3 is sync and the response body is an ``EventStream`` that blocks on
``iter_lines()``; we isolate those blocking calls in a worker thread via
``anyio.to_thread.run_sync`` so the FastAPI event loop stays responsive.

The retry envelope lives in T04 (services/agent.py). This module surfaces
failures as ``AgentRuntimeError(reason=...)`` so the service layer can map
reason strings to retry / fallback decisions without knowing about botocore.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, Protocol

import anyio

from app.config import Settings, get_settings

logger = logging.getLogger("ov_black.agent.bedrock")


class AgentRuntimeError(Exception):
    """Domain error raised when the AgentCore upstream fails.

    ``reason`` is a short stable string the service layer switches on to
    decide between retry, fallback, or propagating upstream_unavailable.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentRuntimeClient(Protocol):
    """Seam the agent service depends on.

    ``invoke_stream`` yields decoded events from the SSE body as dicts of
    one of three shapes:
      - ``{"type": "first_token", "ms": <int>}`` — emitted once, at the first
        text delta, carrying milliseconds since the call started.
      - ``{"type": "delta", "text": <str>}`` — a text chunk.
      - ``{"type": "done", ...}`` — terminal event; caller should stop
        iterating after seeing this.

    ``create_event`` persists a best-effort conversation pair into the
    AgentCore Memory scratchpad for a session. The service layer swallows
    failures — a memory-write crash must never fail a turn.
    """

    def invoke_stream(
        self,
        *,
        agentcore_session_id: str,
        payload: dict,
    ) -> AsyncIterator[dict]:
        ...

    async def create_event(
        self,
        *,
        memory_id: str,
        agentcore_session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        ...


def _parse_sse_line(line: bytes | str) -> dict | None:
    """Parse one ``data: {...}`` SSE line into a dict.

    Returns ``None`` for non-data frames (comments, empty keep-alives) and
    for malformed JSON — the caller emits a WARN and skips. Anything that
    parses into a non-dict value is treated as malformed.
    """
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = line
    text = text.strip()
    if not text or not text.startswith("data:"):
        return None
    payload = text[len("data:") :].strip()
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("agent.runtime.malformed_sse")
        return None
    if not isinstance(decoded, dict):
        logger.warning("agent.runtime.malformed_sse")
        return None
    return decoded


class Boto3AgentRuntimeClient:
    """Real ``AgentRuntimeClient`` backed by ``boto3.client('bedrock-agentcore')``.

    Client construction is **lazy** — we don't touch AWS credentials at
    import time, and we don't touch them at constructor time either. The
    first call to ``invoke_stream`` builds the client. This keeps the unit
    tests offline (they never call ``invoke_stream``) and makes the FastAPI
    lifespan warmup in T05 an explicit opt-in step.
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None

    def _build_client(self) -> Any:
        # Imported lazily so boto3 is only loaded when the real client is
        # actually built — mock-backed tests never pay the import cost.
        import boto3
        from botocore.config import Config

        return boto3.client(
            "bedrock-agentcore",
            region_name=self._settings.aws_region,
            config=Config(retries={"mode": "adaptive", "max_attempts": 1}),
        )

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def invoke_stream(
        self,
        *,
        agentcore_session_id: str,
        payload: dict,
    ) -> AsyncIterator[dict]:
        arn = self._settings.bedrock_agentcore_runtime_arn
        if not arn:
            raise AgentRuntimeError(reason="runtime_arn_unset")

        client = self._ensure_client()
        started_ms = time.monotonic()
        encoded = json.dumps(payload).encode("utf-8")

        def _invoke() -> Any:
            return client.invoke_agent_runtime(
                agentRuntimeArn=arn,
                runtimeSessionId=agentcore_session_id,
                payload=encoded,
                contentType="application/json",
                accept="text/event-stream",
            )

        try:
            response = await anyio.to_thread.run_sync(_invoke)
        except Exception as exc:  # noqa: BLE001 — map any botocore error uniformly
            raise AgentRuntimeError(reason=exc.__class__.__name__) from exc

        body = response.get("response") or response.get("body") or response.get("payload")
        if body is None:
            raise AgentRuntimeError(reason="missing_body")

        iter_lines = getattr(body, "iter_lines", None)
        if not callable(iter_lines):
            raise AgentRuntimeError(reason="non_streaming_body")

        first_token_emitted = False
        async for line in _aiter_lines(iter_lines()):
            parsed = _parse_sse_line(line)
            if parsed is None:
                continue
            kind = parsed.get("type")
            if kind == "delta" and not first_token_emitted:
                first_token_emitted = True
                elapsed_ms = int((time.monotonic() - started_ms) * 1000)
                yield {"type": "first_token", "ms": elapsed_ms}
            yield parsed
            if kind == "done":
                return

        # Stream ended without a terminal ``done`` event. Synthesize one so
        # downstream code always sees a clean terminator.
        yield {"type": "done", "reason": "stream_closed"}

    async def create_event(
        self,
        *,
        memory_id: str,
        agentcore_session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Best-effort AgentCore Memory CreateEvent call. Sync boto3 offloaded."""
        client = self._ensure_client()
        payload = [
            {"conversational": {"content": user_text, "role": "USER"}},
            {"conversational": {"content": assistant_text, "role": "ASSISTANT"}},
        ]

        def _create() -> Any:
            return client.create_event(
                memoryId=memory_id,
                sessionId=agentcore_session_id,
                payload=payload,
            )

        try:
            await anyio.to_thread.run_sync(_create)
        except Exception as exc:  # noqa: BLE001 — map to domain error for caller
            raise AgentRuntimeError(reason=exc.__class__.__name__) from exc


async def _aiter_lines(lines: Iterable[Any]) -> AsyncIterator[Any]:
    """Pull each ``line`` off a sync iterator inside a worker thread.

    boto3's ``EventStream`` yields bytes synchronously — calling ``next()``
    blocks the thread until the next SSE chunk arrives. We offload each
    step to ``anyio.to_thread.run_sync`` so the event loop keeps turning.
    """
    iterator = iter(lines)
    sentinel = object()

    def _next() -> Any:
        try:
            return next(iterator)
        except StopIteration:
            return sentinel

    while True:
        value = await anyio.to_thread.run_sync(_next)
        if value is sentinel:
            return
        yield value


class LocalAgentRuntimeClient:
    """HTTP-backed AgentRuntimeClient that talks to a local ``apps/agent``.

    Used for local development: set ``AGENT_LOCAL_URL`` (e.g.
    ``http://localhost:8080``) and the FastAPI lifespan wires this
    client instead of Boto3 or the mock. It POSTs to ``/invocations``
    with the payload and parses the ``data: ...\\n\\n`` SSE body the
    runtime emits.

    No AWS dependency. Honors the same event shape as the real
    AgentCore runtime, so downstream dispatch logic in stream_turn is
    unchanged.
    """

    def __init__(self, *, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def invoke_stream(
        self,
        *,
        agentcore_session_id: str,
        payload: dict,
    ) -> AsyncIterator[dict]:
        import httpx

        started = time.monotonic()
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            # BedrockAgentCoreApp reads this header to resolve the session.
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": agentcore_session_id,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/invocations",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        raise AgentRuntimeError(
                            reason=f"http_{response.status_code}"
                        )
                    first_token_emitted = False
                    async for line in response.aiter_lines():
                        parsed = _parse_sse_line(line.encode("utf-8"))
                        if parsed is None:
                            continue
                        kind = parsed.get("type")
                        if kind == "delta" and not first_token_emitted:
                            first_token_emitted = True
                            elapsed_ms = int((time.monotonic() - started) * 1000)
                            yield {"type": "first_token", "ms": elapsed_ms}
                        yield parsed
                        if kind == "done":
                            return
        except httpx.HTTPError as exc:
            raise AgentRuntimeError(reason=exc.__class__.__name__) from exc

        yield {"type": "done", "reason": "stream_closed"}

    async def create_event(
        self,
        *,
        memory_id: str,
        agentcore_session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        """No-op — local runtime has no AgentCore Memory backend."""
        return None


class MockAgentRuntimeClient:
    """Scripted ``AgentRuntimeClient`` for unit tests.

    Pass a sequence of pre-built event dicts; ``invoke_stream`` yields them
    verbatim in order. The mock does NOT auto-inject a ``first_token``
    event — test authors script the exact wire trace they want to assert.

    ``events`` can also be a callable returning an iterable — the callable
    is invoked fresh on every ``invoke_stream`` call so tests can script
    per-call scripts (e.g. first attempt raises, second attempt streams).
    ``raise_on_invoke`` lets a test sequence exceptions across attempts.
    """

    def __init__(
        self,
        events: Sequence[dict] | list[Sequence[dict]] | None = None,
        *,
        raise_on_invoke: Sequence[BaseException | None] | None = None,
    ) -> None:
        self._events = events or []
        self._raises = list(raise_on_invoke) if raise_on_invoke else []
        self.calls: list[dict] = []
        self.create_event_calls: list[dict] = []
        self.create_event_raises: BaseException | None = None

    def _script_for_call(self, attempt_index: int) -> Sequence[dict]:
        events = self._events
        # Per-call scripts: list of lists.
        if events and isinstance(events[0], list):
            idx = min(attempt_index, len(events) - 1)
            return events[idx]
        return events  # type: ignore[return-value]

    async def invoke_stream(
        self,
        *,
        agentcore_session_id: str,
        payload: dict,
    ) -> AsyncIterator[dict]:
        attempt_index = len(self.calls)
        self.calls.append(
            {
                "agentcore_session_id": agentcore_session_id,
                "payload": payload,
            }
        )
        if attempt_index < len(self._raises):
            exc = self._raises[attempt_index]
            if exc is not None:
                raise exc
        for event in self._script_for_call(attempt_index):
            yield event

    async def create_event(
        self,
        *,
        memory_id: str,
        agentcore_session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self.create_event_calls.append(
            {
                "memory_id": memory_id,
                "agentcore_session_id": agentcore_session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
            }
        )
        if self.create_event_raises is not None:
            raise self.create_event_raises
