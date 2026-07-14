"""The ``suggest_reading`` tool + its ``surface`` (kind=article) frame mapping.

Offline: the one HTTP hop — ``GET /agent/reading/search`` via
``agent_get_json`` — is monkeypatched on the reading module. The tool is
basecamp-only: it self-gates to unpinned, traveler-audience sessions, so the
pin contextvar decides whether it searches or declines. The translate
assertion proves a hit reaches the browser as an ``article`` surface frame.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import reading as reading_mod
from agent.translate import translate_event

_HIT: dict[str, Any] = {
    "id": "art-1",
    "title": "The Granite Spires of Patagonia",
    "url": "https://www.climbing.com/places/patagonia/",
    "source_property": "Climbing",
    "og_image": "https://images.unsplash.com/photo-1496340077100-9573d8b77463?w=1200",
    "excerpt": "Fitz Roy and Cerro Torre still set the standard.",
    "reading_time_minutes": 11,
}


def _basecamp_pin() -> dict[str, Any]:
    return {
        "client_id": "client-1",
        "itinerary_id": None,
        "actor_kind": "user",
        "audience": "traveler",
    }


@pytest.fixture()
def basecamp_session() -> Iterator[None]:
    token = pin_ctx.set(_basecamp_pin())
    try:
        yield
    finally:
        pin_ctx.reset(token)


def _capture(monkeypatch: pytest.MonkeyPatch, results: list[dict]) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        calls.append((path, params))
        return {"results": results}

    monkeypatch.setattr(reading_mod, "agent_get_json", _get)
    return calls


async def test_suggest_reading_shapes_article_surface(
    monkeypatch: pytest.MonkeyPatch, basecamp_session: None
) -> None:
    calls = _capture(monkeypatch, [_HIT])
    result = await reading_mod.suggest_reading._tool_func(query="patagonia climbing")

    path, params = calls[-1]
    assert path == "/agent/reading/search"
    assert params == {"q": "patagonia climbing", "limit": 3}

    assert result["kind"] == "article"
    assert result["surface_id"].startswith("srf-")
    payload = result["payload"]
    assert payload["title"] == _HIT["title"]
    assert payload["url"] == _HIT["url"]
    assert payload["publication"] == "Climbing"
    assert payload["og_image"] == _HIT["og_image"]
    assert payload["reading_time_minutes"] == 11


async def test_suggest_reading_declines_when_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch, [_HIT])
    token = pin_ctx.set({**_basecamp_pin(), "itinerary_id": "itin-1"})
    try:
        result = await reading_mod.suggest_reading._tool_func(query="patagonia")
    finally:
        pin_ctx.reset(token)
    assert result == {"error": "only_in_basecamp"}
    assert calls == []  # never reached the backend


async def test_suggest_reading_declines_for_non_traveler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture(monkeypatch, [_HIT])
    token = pin_ctx.set({**_basecamp_pin(), "audience": "advisor"})
    try:
        result = await reading_mod.suggest_reading._tool_func(query="patagonia")
    finally:
        pin_ctx.reset(token)
    assert result == {"error": "only_for_traveler"}
    assert calls == []


async def test_suggest_reading_no_results_returns_error(
    monkeypatch: pytest.MonkeyPatch, basecamp_session: None
) -> None:
    _capture(monkeypatch, [])
    result = await reading_mod.suggest_reading._tool_func(query="nothing matches")
    assert result == {"error": "no_reading_found"}


async def test_suggest_reading_backend_error_returns_reason(
    monkeypatch: pytest.MonkeyPatch, basecamp_session: None
) -> None:
    async def _get(path: str, *, params: dict | None = None) -> Any:
        raise BackendError(status=502, reason="reading_upstream_error")

    monkeypatch.setattr(reading_mod, "agent_get_json", _get)
    result = await reading_mod.suggest_reading._tool_func(query="patagonia")
    assert result == {"error": "reading_upstream_error"}


def test_translate_surface_frame_for_article() -> None:
    output = {
        "surface_id": "srf-read",
        "kind": "article",
        "payload": {"title": "T", "url": "https://x.test/a", "publication": "Outside"},
    }
    event = {"tool_result": {"toolName": "suggest_reading", "output": output}}
    frames = list(translate_event(event))
    assert {
        "type": "surface",
        "surface_id": "srf-read",
        "kind": "article",
        "payload": {"title": "T", "url": "https://x.test/a", "publication": "Outside"},
    } in frames
