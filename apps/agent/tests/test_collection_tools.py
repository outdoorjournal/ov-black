"""Collection (wish list) tools + their SSE frame mappings.

Offline (no backend): monkeypatch the ``post_json`` / ``get_json`` the
``collection`` tool module imported, drive each tool's underlying coroutine
(``_tool_func``), and assert the request it builds. The translate assertions
prove a Collection write surfaces to the browser as a ``card_proposed`` frame.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import collection as collection_mod
from agent.translate import translate_event


def _pin(itinerary_id: str | None = "it-1") -> dict[str, Any]:
    return {
        "client_id": "client-9",
        "itinerary_id": itinerary_id,
        "actor_kind": "user",
        "audience": "traveler",
    }


def _capture_post(monkeypatch: pytest.MonkeyPatch, *, created_id: str = "new-it") -> list[tuple[str, Any]]:
    """Record post_json calls; answer the auto-create POST /itinerary."""
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        if path == "/itinerary":
            return {"id": created_id}
        return {"id": "node-1", **(json or {})}

    monkeypatch.setattr(collection_mod, "post_json", _post)
    return calls


async def test_save_to_collection_posts_from_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_post(monkeypatch)
    token = pin_ctx.set(_pin())
    try:
        await collection_mod.save_to_collection._tool_func(source="google_places", source_id="pl-9")
        path, body = calls[-1]
        assert path == "/itinerary/it-1/nodes/from-inventory"
        assert body == {"source": "google_places", "source_id": "pl-9"}
    finally:
        pin_ctx.reset(token)


async def test_save_to_collection_auto_creates_and_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_post(monkeypatch, created_id="auto-it")
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        await collection_mod.save_to_collection._tool_func(source="duffel", source_id="off-1")
        # First creates an itinerary, then posts the item to it.
        assert calls[0][0] == "/itinerary"
        assert calls[-1][0] == "/itinerary/auto-it/nodes/from-inventory"
        # The session is now pinned so the next turn runs in planning mode.
        assert (pin_ctx.get() or {}).get("itinerary_id") == "auto-it"
    finally:
        pin_ctx.reset(token)


async def test_save_link_to_collection_posts_from_link(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_post(monkeypatch)
    token = pin_ctx.set(_pin())
    try:
        await collection_mod.save_link_to_collection._tool_func(
            url="https://kikunoi.jp/", kind="meal", note="anniversary dinner"
        )
        path, body = calls[-1]
        assert path == "/itinerary/it-1/nodes/from-link"
        assert body == {"url": "https://kikunoi.jp/", "kind": "meal", "note": "anniversary dinner"}
    finally:
        pin_ctx.reset(token)


async def test_save_link_defaults_kind_note_and_omits_note(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_post(monkeypatch)
    token = pin_ctx.set(_pin())
    try:
        await collection_mod.save_link_to_collection._tool_func(url="https://example.com/x")
        _, body = calls[-1]
        assert body == {"url": "https://example.com/x", "kind": "note"}
    finally:
        pin_ctx.reset(token)


async def test_add_collection_note_posts_timeless_note(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_post(monkeypatch)
    token = pin_ctx.set(_pin())
    try:
        await collection_mod.add_collection_note._tool_func(text="wants a sushi counter, not a table")
        path, body = calls[-1]
        assert path == "/itinerary/it-1/nodes"
        # No starts_at / attached_to_node_id → a timeless Collection note.
        assert body == {
            "type": "note",
            "status": "pending",
            "title": "wants a sushi counter, not a table",
        }
    finally:
        pin_ctx.reset(token)


async def test_get_collection_reads_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append(path)
        return {"itinerary_id": "it-1", "items": []}

    monkeypatch.setattr(collection_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        await collection_mod.get_collection._tool_func()
        assert seen[-1] == "/itinerary/it-1/collection"
    finally:
        pin_ctx.reset(token)


async def test_get_collection_honors_explicit_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append(path)
        return {"itinerary_id": "other", "items": []}

    monkeypatch.setattr(collection_mod, "get_json", _get)
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        await collection_mod.get_collection._tool_func(itinerary_id="other")
        assert seen[-1] == "/itinerary/other/collection"
    finally:
        pin_ctx.reset(token)


async def test_get_collection_without_target_raises() -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await collection_mod.get_collection._tool_func()
        assert exc.value.reason == "missing_itinerary_id"
    finally:
        pin_ctx.reset(token)


@pytest.mark.parametrize(
    "tool_name",
    ["save_to_collection", "save_link_to_collection", "add_collection_note"],
)
def test_collection_writes_map_to_card_proposed(tool_name: str) -> None:
    event = {"tool_result": {"name": tool_name, "output": {"id": "n1", "title": "Kikunoi"}}}
    frames = list(translate_event(event))
    assert [f for f in frames if f.get("type") != "activity"] == [
        {"type": "card_proposed", "node": {"id": "n1", "title": "Kikunoi"}}
    ]
