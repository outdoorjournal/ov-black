"""The traveler-feedback tools: ``add_note`` (attached / free-standing) + ``move_node``.

Offline (no backend): monkeypatch the ``post_json`` / ``get_json`` / ``patch_json``
the tool modules imported, drive each tool's underlying coroutine (``_tool_func``),
and assert the request it builds.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import mutations as mutations_mod
from agent.tools import notes as notes_mod


def _pin(itinerary_id: str | None = "it-1") -> dict[str, Any]:
    return {
        "client_id": "client-9",
        "itinerary_id": itinerary_id,
        "actor_kind": "user",
        "audience": "traveler",
    }


async def test_add_note_attached_posts_attached_to_node_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "note-1", "type": "note"}

    monkeypatch.setattr(notes_mod, "post_json", _post)
    token = pin_ctx.set(_pin())
    try:
        await notes_mod.add_note._tool_func(text="why are we doing this at 1:30?", node_id="n-7")
        path, body = calls[-1]
        assert path == "/itinerary/it-1/nodes"
        assert body == {
            "type": "note",
            "status": "proposed",
            "title": "why are we doing this at 1:30?",
            "attached_to_node_id": "n-7",
        }
    finally:
        pin_ctx.reset(token)


async def test_add_note_free_standing_posts_starts_at(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "note-2", "type": "note"}

    monkeypatch.setattr(notes_mod, "post_json", _post)
    token = pin_ctx.set(_pin())
    try:
        await notes_mod.add_note._tool_func(
            text="something for dinner between these",
            starts_at="2025-07-02T19:30:00+09:00",
        )
        _, body = calls[-1]
        assert body["starts_at"] == "2025-07-02T19:30:00+09:00"
        assert "attached_to_node_id" not in body
    finally:
        pin_ctx.reset(token)


async def test_add_note_without_anchor_raises() -> None:
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as exc:
            await notes_mod.add_note._tool_func(text="floating")
        assert exc.value.reason == "note_needs_anchor"
    finally:
        pin_ctx.reset(token)


async def test_add_note_without_pin_raises() -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await notes_mod.add_note._tool_func(text="x", node_id="n-1")
        assert exc.value.reason == "no_itinerary_pinned"
    finally:
        pin_ctx.reset(token)


async def test_move_node_merges_metadata_and_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    patched: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        return {
            "nodes": [
                {"id": "n-1", "metadata": {"snapshot": {"title": "Dinner"}, "duration_minutes": 90}},
                {"id": "n-2", "metadata": {}},
            ]
        }

    async def _patch(path: str, *, json: dict | None = None) -> Any:
        patched.append((path, json))
        return {"id": "n-1"}

    monkeypatch.setattr(mutations_mod, "get_json", _get)
    monkeypatch.setattr(mutations_mod, "patch_json", _patch)
    token = pin_ctx.set(_pin())
    try:
        await mutations_mod.move_node._tool_func("n-1", "2025-07-02T20:00:00+09:00")
        path, body = patched[-1]
        assert path == "/itinerary/it-1/nodes/n-1"
        # Existing metadata is preserved; only start_time changes.
        assert body["metadata"] == {
            "snapshot": {"title": "Dinner"},
            "duration_minutes": 90,
            "start_time": "2025-07-02T20:00:00+09:00",
        }
    finally:
        pin_ctx.reset(token)


async def test_move_node_unknown_node_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _get(path: str, *, params: dict | None = None) -> Any:
        return {"nodes": []}

    monkeypatch.setattr(mutations_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as exc:
            await mutations_mod.move_node._tool_func("missing", "2025-07-02T20:00:00+09:00")
        assert exc.value.reason == "not_found"
    finally:
        pin_ctx.reset(token)
