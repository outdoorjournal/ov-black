"""Presentation-surface tools (``present_route`` / ``present_options``) +
their ``surface`` SSE frame mapping.

Offline (no backend): ``present_route``'s one HTTP hop — ``POST /agent/route``
via ``agent_post_json`` — is monkeypatched on the surfaces module; everything
else is pure. The translate assertions prove a tool result reaches the
browser as ``{"type": "surface", surface_id, kind, payload}`` and that error
results are dropped rather than rendered.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError
from agent.tools import surfaces as surfaces_mod
from agent.translate import translate_event

_PLAN: dict[str, Any] = {
    "origin": "Tokyo Station",
    "destination": "Hakone",
    "waypoints": [],
    "mode": "drive",
    "distance_meters": 96432,
    "duration_seconds": 5411,
    "encoded_polyline": "abc123",
    "legs": [],
}


def _capture_route(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return dict(_PLAN)

    monkeypatch.setattr(surfaces_mod, "agent_post_json", _post)
    return calls


# ── present_route ────────────────────────────────────────────────────────


async def test_present_route_calls_backend_and_shapes_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_route(monkeypatch)
    result = await surfaces_mod.present_route._tool_func(
        origin="Tokyo Station",
        destination="Hakone",
        headline="The mountain road",
        highlights=[{"title": "Odawara castle", "detail": "worth a pause"}],
    )
    path, body = calls[-1]
    assert path == "/agent/route"
    assert body == {
        "origin": "Tokyo Station",
        "destination": "Hakone",
        "waypoints": [],
        "mode": "drive",
    }
    assert result["kind"] == "route"
    assert result["surface_id"].startswith("srf-")
    assert result["payload"]["route"]["encoded_polyline"] == "abc123"
    assert result["payload"]["headline"] == "The mountain road"
    assert result["payload"]["highlights"] == [
        {"title": "Odawara castle", "detail": "worth a pause"}
    ]


async def test_present_route_backend_error_returns_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _post(path: str, *, json: dict | None = None) -> Any:
        raise BackendError(status=404, reason="route_not_found")

    monkeypatch.setattr(surfaces_mod, "agent_post_json", _post)
    result = await surfaces_mod.present_route._tool_func(origin="Honolulu", destination="Tokyo")
    assert result == {"error": "route_not_found"}


async def test_present_route_rejects_bad_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_route(monkeypatch)
    result = await surfaces_mod.present_route._tool_func(
        origin="A", destination="B", mode="teleport"
    )
    assert result == {"error": "invalid_route_args"}
    assert calls == []  # never reached the backend


# ── present_options ──────────────────────────────────────────────────────


async def test_present_options_shapes_and_assigns_ids() -> None:
    result = await surfaces_mod.present_options._tool_func(
        question="Which base for the Kii peninsula?",
        options=[
            {"title": "Ryokan Sasayuri-an", "tagline": "three rooms", "case": "Quietest."},
            {"title": "Koyasan temple stay", "node_id": "node-7"},
        ],
        context="Both hold availability for your dates.",
    )
    assert result["kind"] == "options"
    payload = result["payload"]
    assert payload["question"] == "Which base for the Kii peninsula?"
    assert payload["context"] == "Both hold availability for your dates."
    first, second = payload["options"]
    assert first == {
        "id": "opt-1",
        "title": "Ryokan Sasayuri-an",
        "tagline": "three rooms",
        "case": "Quietest.",
    }
    assert second == {"id": "opt-2", "title": "Koyasan temple stay", "node_id": "node-7"}


async def test_present_options_rejects_single_option() -> None:
    result = await surfaces_mod.present_options._tool_func(
        question="Just one?", options=[{"title": "Only choice"}]
    )
    assert result == {"error": "invalid_options"}


# ── translate → surface frame ────────────────────────────────────────────


def _tool_result_event(name: str, output: dict[str, Any]) -> dict[str, Any]:
    return {"tool_result": {"toolName": name, "output": output}}


def test_translate_surface_frame_for_route() -> None:
    output = {
        "surface_id": "srf-abc",
        "kind": "route",
        "payload": {"route": dict(_PLAN), "headline": "South"},
    }
    frames = list(translate_event(_tool_result_event("present_route", output)))
    surface = [f for f in frames if f["type"] == "surface"]
    assert surface == [
        {
            "type": "surface",
            "surface_id": "srf-abc",
            "kind": "route",
            "payload": {"route": dict(_PLAN), "headline": "South"},
        }
    ]


def test_translate_surface_frame_for_options() -> None:
    output = {
        "surface_id": "srf-def",
        "kind": "options",
        "payload": {"question": "A or B?", "options": [{"id": "opt-1", "title": "A"}]},
    }
    frames = list(translate_event(_tool_result_event("present_options", output)))
    assert any(f["type"] == "surface" and f["kind"] == "options" for f in frames)


def test_translate_drops_error_and_malformed_surfaces() -> None:
    for output in (
        {"error": "route_not_found"},
        {"kind": "route"},  # no payload
        {"payload": {}},  # no kind
    ):
        frames = list(translate_event(_tool_result_event("present_route", output)))
        assert all(f["type"] != "surface" for f in frames)
