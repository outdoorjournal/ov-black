"""G3 — the conversational fork tools: re-pin, request-reconcile, reconcile.

Offline (no backend): we monkeypatch the ``post_json`` / ``get_json`` the tool
modules imported, drive each tool's underlying coroutine (``_tool_func``), and
assert the request it builds + the re-pin side effect.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.schemas import Mode
from agent.tools import fork as fork_mod
from agent.tools import reconcile as reconcile_mod
from agent.tools import tools_for

# ``agent.tools.request_reconcile`` (the submodule) is shadowed in the package
# namespace by the same-named tool function, so reach the module via sys.modules.
request_mod = sys.modules["agent.tools.request_reconcile"]


def _names(mode: Mode) -> set[str]:
    return {t.tool_name for t in tools_for(mode)}


def test_planning_bundle_has_fork_and_reconcile_tools() -> None:
    planning = _names(Mode.planning)
    assert {"fork_itinerary", "request_reconcile", "reconcile_alternative"} <= planning
    # Read-only Q&A never reconciles or requests a merge.
    qa = _names(Mode.qa)
    assert "reconcile_alternative" not in qa
    assert "request_reconcile" not in qa


async def test_fork_tool_repins_session_to_alternative(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        if path.endswith("/fork"):
            return {"itinerary": {"id": "fork-123", "forked_from_id": "base-1"}, "nodes": []}
        return {"id": "sess-1"}

    monkeypatch.setattr(fork_mod, "post_json", _post)
    token = pin_ctx.set(
        {
            "client_id": "client-9",
            "itinerary_id": "base-1",
            "actor_kind": "user",
            "audience": "traveler",
        }
    )
    try:
        result = await fork_mod.fork_itinerary._tool_func(title="Slower version")
        assert result["itinerary"]["id"] == "fork-123"
        # It forked the pinned baseline, then re-pinned the session to the fork.
        assert ("/itinerary/base-1/fork", {"title": "Slower version"}) in calls
        repin = next(c for p, c in calls if p == "/sessions")
        assert repin == {
            "client_id": "client-9",
            "itinerary_id": "fork-123",
            "audience": "traveler",
        }
        # In-process pin now targets the alternative for the rest of the turn.
        assert pin_ctx.get()["itinerary_id"] == "fork-123"
    finally:
        pin_ctx.reset(token)


async def test_fork_tool_survives_repin_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _post(path: str, *, json: dict | None = None) -> Any:
        if path.endswith("/fork"):
            return {"itinerary": {"id": "fork-9"}, "nodes": []}
        raise BackendError(status=500, reason="boom")  # re-pin POST /sessions fails

    monkeypatch.setattr(fork_mod, "post_json", _post)
    token = pin_ctx.set(
        {"client_id": "c1", "itinerary_id": "base", "actor_kind": "user", "audience": "traveler"}
    )
    try:
        result = await fork_mod.fork_itinerary._tool_func()
        # The fork still succeeds; in-process re-pin still applies for this turn.
        assert result["itinerary"]["id"] == "fork-9"
        assert pin_ctx.get()["itinerary_id"] == "fork-9"
    finally:
        pin_ctx.reset(token)


async def test_request_reconcile_tool_posts_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "fork-1", "reconcile_requested_at": "2026-06-26T00:00:00Z"}

    monkeypatch.setattr(request_mod, "post_json", _post)
    token = pin_ctx.set(
        {"client_id": "c", "itinerary_id": "fork-1", "actor_kind": "user", "audience": "traveler"}
    )
    try:
        await request_mod.request_reconcile._tool_func(note="prefer slower")
        assert calls == [("/itinerary/fork-1/request-reconcile", {"note": "prefer slower"})]
    finally:
        pin_ctx.reset(token)


async def test_reconcile_alternative_refuses_a_traveler() -> None:
    token = pin_ctx.set(
        {"client_id": "c", "itinerary_id": "fork-1", "actor_kind": "user", "audience": "traveler"}
    )
    try:
        with pytest.raises(BackendError) as exc:
            await reconcile_mod.reconcile_alternative._tool_func()
        assert exc.value.status == 403
        assert exc.value.reason == "advisor_only"
    finally:
        pin_ctx.reset(token)


async def test_reconcile_alternative_accept_all_builds_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        return {
            "added": [{"change_id": "a1"}],
            "removed": [{"change_id": "r1"}],
            "changed": [{"change_id": "c1"}],
            "moved": [],
        }

    async def _post(path: str, *, json: dict | None = None) -> Any:
        posted.append((path, json))
        return {"baseline": {}, "fork": {}, "outcomes": []}

    monkeypatch.setattr(reconcile_mod, "get_json", _get)
    monkeypatch.setattr(reconcile_mod, "post_json", _post)
    token = pin_ctx.set(
        {"client_id": "c", "itinerary_id": "fork-7", "actor_kind": "advisor", "audience": "advisor"}
    )
    try:
        await reconcile_mod.reconcile_alternative._tool_func(action="accept_all")
        path, body = posted[-1]
        assert path == "/itinerary/fork-7/reconcile"
        ids = {d["change_id"] for d in body["decisions"]}
        assert ids == {"a1", "r1", "c1"}
        assert all(d["accept"] for d in body["decisions"])
    finally:
        pin_ctx.reset(token)


async def test_reconcile_alternative_abandon(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        posted.append(path)
        return {"id": "fork-7", "fork_status": "abandoned"}

    monkeypatch.setattr(reconcile_mod, "post_json", _post)
    token = pin_ctx.set(
        {"client_id": "c", "itinerary_id": "fork-7", "actor_kind": "advisor", "audience": "advisor"}
    )
    try:
        await reconcile_mod.reconcile_alternative._tool_func(action="abandon")
        assert posted == ["/itinerary/fork-7/abandon"]
    finally:
        pin_ctx.reset(token)
