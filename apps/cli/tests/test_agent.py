"""Agent turn collection over a fake SSE transport."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from ovb.agent import run_turn
from ovb.errors import ApiError, TurnError
from ovb.sdk import Ovb


class _FakeResp:
    def __init__(self, status_code: int, chunks: list[str], body: Any = None) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self._body = body

    async def aiter_text(self) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return b""

    def json(self) -> Any:
        return self._body


class _FakeTransport:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp
        self.calls: list[tuple[str, str, Any]] = []

    @asynccontextmanager
    async def stream(self, method: str, path: str, *, json_body: Any = None, **_: Any):  # type: ignore[no-untyped-def]
        self.calls.append((method, path, json_body))
        yield self._resp


def _ovb(resp: _FakeResp) -> Ovb:
    return Ovb(_FakeTransport(resp))  # type: ignore[arg-type]


async def test_run_turn_collects_text_first_token_and_proposed_node() -> None:
    chunks = [
        'data: {"type":"first_token","ms":12}\n\n',
        'data: {"type":"delta","text":"He"}\n\n',
        'data: {"type":"delta","text":"llo"}\n\n',
        'data: {"type":"card_proposed",'
        '"node":{"id":"n1","itinerary_id":"itin-1","title":"Aman"}}\n\n',
        'data: {"type":"done","turn_id":"t1","latency_ms":5}\n\n',
    ]
    result = await run_turn(_ovb(_FakeResp(200, chunks)), "s1", "hi")
    assert result.content == "Hello"
    assert result.first_token_ms == 12
    assert result.turn_id == "t1"
    assert result.ok
    assert result.proposed_nodes == [{"id": "n1", "itinerary_id": "itin-1", "title": "Aman"}]


async def test_run_turn_split_frame_across_chunks() -> None:
    chunks = [
        'data: {"type":"delta","te',
        'xt":"split"}\n\ndata: {"type":"done","turn_id":"t2"}\n\n',
    ]
    result = await run_turn(_ovb(_FakeResp(200, chunks)), "s1", "hi")
    assert result.content == "split" and result.turn_id == "t2"


async def test_run_turn_error_frame() -> None:
    chunks = ['data: {"type":"error","reason":"upstream_unavailable"}\n\n']
    result = await run_turn(_ovb(_FakeResp(200, chunks)), "s1", "hi")
    assert not result.ok and result.error is not None
    assert result.error.reason == "upstream_unavailable"
    with pytest.raises(TurnError):
        await run_turn(_ovb(_FakeResp(200, chunks)), "s1", "hi", raise_on_error=True)


async def test_pre_stream_non_200_raises_apierror() -> None:
    resp = _FakeResp(404, [], body={"detail": "session_not_found"})
    with pytest.raises(ApiError) as exc:
        await run_turn(_ovb(resp), "s1", "hi")
    assert exc.value.status == 404 and exc.value.detail == "session_not_found"
