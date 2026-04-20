"""Unit tests for ``app.agent.bedrock``.

Offline-only. The Boto3 client is never actually constructed — we assert
that it's lazy (constructor doesn't need AWS creds) and exercise the
public event-dict contract via ``MockAgentRuntimeClient`` and by
round-tripping the SSE line parser.
"""

from __future__ import annotations

import logging

import pytest

from app.agent.bedrock import (
    AgentRuntimeError,
    Boto3AgentRuntimeClient,
    MockAgentRuntimeClient,
    _parse_sse_line,
)
from app.config import Settings


def test_boto3_client_constructs_without_aws_credentials() -> None:
    """Constructor is lazy — no AWS env vars required, no client built yet."""
    settings = Settings(
        aws_region="us-west-2",
        bedrock_agentcore_runtime_arn="",
    )
    client = Boto3AgentRuntimeClient(settings=settings)
    # The internal ``_client`` attribute stays None until invoke_stream runs.
    assert client._client is None


async def test_boto3_client_raises_when_runtime_arn_missing() -> None:
    """Runtime ARN unset → AgentRuntimeError(reason='runtime_arn_unset')."""
    settings = Settings(
        aws_region="us-west-2",
        bedrock_agentcore_runtime_arn="",
    )
    client = Boto3AgentRuntimeClient(settings=settings)

    with pytest.raises(AgentRuntimeError) as excinfo:
        async for _ in client.invoke_stream(
            agentcore_session_id="session-xyz",
            payload={"prompt": "hi"},
        ):
            pass  # pragma: no cover — generator should raise before yielding
    assert excinfo.value.reason == "runtime_arn_unset"


async def test_mock_client_round_trips_scripted_stream() -> None:
    """MockAgentRuntimeClient yields its scripted events verbatim, in order."""
    script = [
        {"type": "first_token", "ms": 420},
        {"type": "delta", "text": "Hel"},
        {"type": "delta", "text": "lo"},
        {"type": "done", "usage": {"input_tokens": 12}},
    ]
    client = MockAgentRuntimeClient(script)

    received: list[dict] = []
    async for event in client.invoke_stream(
        agentcore_session_id="s-1",
        payload={"prompt": "hello"},
    ):
        received.append(event)

    assert received == script
    # The mock records what it was called with so assertions can inspect it.
    assert client.calls == [
        {"agentcore_session_id": "s-1", "payload": {"prompt": "hello"}}
    ]


async def test_mock_client_records_multiple_calls() -> None:
    """Multiple ``invoke_stream`` calls append to the ``calls`` log."""
    client = MockAgentRuntimeClient([{"type": "done"}])

    async for _ in client.invoke_stream(
        agentcore_session_id="s-1", payload={"t": 1}
    ):
        pass
    async for _ in client.invoke_stream(
        agentcore_session_id="s-2", payload={"t": 2}
    ):
        pass

    assert [call["agentcore_session_id"] for call in client.calls] == ["s-1", "s-2"]


class TestParseSseLine:
    """Line-level parsing contract for the streaming body."""

    def test_parses_well_formed_data_line(self) -> None:
        result = _parse_sse_line(b'data: {"type":"delta","text":"hi"}')
        assert result == {"type": "delta", "text": "hi"}

    def test_accepts_str_and_bytes_input(self) -> None:
        assert _parse_sse_line('data: {"type":"done"}') == {"type": "done"}
        assert _parse_sse_line(b'data: {"type":"done"}') == {"type": "done"}

    def test_skips_comment_and_empty_lines(self) -> None:
        assert _parse_sse_line(b": keep-alive") is None
        assert _parse_sse_line(b"") is None
        assert _parse_sse_line(b"data:") is None

    def test_skips_malformed_json_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="ov_black.agent.bedrock")
        assert _parse_sse_line(b"data: {not json") is None
        assert any(
            rec.message == "agent.runtime.malformed_sse" for rec in caplog.records
        )

    def test_skips_non_dict_json_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="ov_black.agent.bedrock")
        # Parsable as JSON, but top-level is a list — we only trust dicts.
        assert _parse_sse_line(b'data: ["not", "a", "dict"]') is None
        assert any(
            rec.message == "agent.runtime.malformed_sse" for rec in caplog.records
        )


async def test_agent_runtime_error_carries_reason() -> None:
    """Domain error surfaces a stable ``reason`` string."""
    err = AgentRuntimeError(reason="timeout")
    assert err.reason == "timeout"
    assert str(err) == "timeout"
