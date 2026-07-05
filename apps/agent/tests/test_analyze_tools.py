"""Analyze tools — queue a feasibility run and read its findings (ADV-6).

Offline (no backend): monkeypatch the ``post_json`` / ``get_json`` the
``analyze`` tool module imported, drive each tool's underlying coroutine
(``_tool_func``), and assert the request it builds + the shape it returns.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import analyze as analyze_mod


def _pin(itinerary_id: str | None = "it-1") -> dict[str, Any]:
    return {
        "client_id": "client-9",
        "itinerary_id": itinerary_id,
        "actor_kind": "advisor",
        "audience": "advisor",
    }


async def test_run_analysis_posts_depth_and_force_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"analysis_id": "an-1", "status": "queued", "cache_hit": False, "in_flight": False}

    monkeypatch.setattr(analyze_mod, "post_json", _post)
    token = pin_ctx.set(_pin())
    try:
        out = await analyze_mod.run_analysis._tool_func(depth="deep", force_rerun=True)
        path, body = calls[-1]
        assert path == "/itinerary/it-1/analyses"
        assert body == {"depth": "deep", "force_rerun": True}
        assert out["analysis_id"] == "an-1"
    finally:
        pin_ctx.reset(token)


async def test_run_analysis_defaults_standard_no_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"analysis_id": "an-2", "status": "queued"}

    monkeypatch.setattr(analyze_mod, "post_json", _post)
    token = pin_ctx.set(_pin())
    try:
        await analyze_mod.run_analysis._tool_func()
        _, body = calls[-1]
        assert body == {"depth": "standard", "force_rerun": False}
    finally:
        pin_ctx.reset(token)


async def test_run_analysis_without_pin_raises() -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await analyze_mod.run_analysis._tool_func()
        assert exc.value.reason == "missing_itinerary_id"
    finally:
        pin_ctx.reset(token)


async def test_get_findings_explicit_id_fetches_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append((path, params))
        return {
            "id": "an-1",
            "status": "completed",
            "depth": "standard",
            "summary": "Two overlaps.",
            "result": {"noisy": "dropped"},
            "external_calls": ["also dropped"],
            "findings": [
                {"id": "f1", "severity": "warn", "category": "overlap", "message": "…"}
            ],
        }

    monkeypatch.setattr(analyze_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        out = await analyze_mod.get_analysis_findings._tool_func(analysis_id="an-1")
        # Fetches the detail directly — no list call.
        assert seen == [("/itinerary/it-1/analyses/an-1", None)]
        # Shaped: status + summary + findings surface; result/external_calls dropped.
        assert out == {
            "analysis_id": "an-1",
            "status": "completed",
            "depth": "standard",
            "summary": "Two overlaps.",
            "findings": [
                {"id": "f1", "severity": "warn", "category": "overlap", "message": "…"}
            ],
        }
    finally:
        pin_ctx.reset(token)


async def test_get_findings_defaults_to_latest_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append((path, params))
        if path.endswith("/analyses"):
            return [{"id": "an-latest", "status": "completed"}]
        return {"id": "an-latest", "status": "completed", "depth": "standard", "summary": None, "findings": []}

    monkeypatch.setattr(analyze_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        out = await analyze_mod.get_analysis_findings._tool_func()
        # Lists (limit=1) to find the newest, then fetches its detail.
        assert seen[0] == ("/itinerary/it-1/analyses", {"limit": 1})
        assert seen[1] == ("/itinerary/it-1/analyses/an-latest", None)
        assert out["analysis_id"] == "an-latest"
    finally:
        pin_ctx.reset(token)


async def test_get_findings_no_runs_returns_none_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(path: str, *, params: dict | None = None) -> Any:
        return []

    monkeypatch.setattr(analyze_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        out = await analyze_mod.get_analysis_findings._tool_func()
        assert out == {"status": "none", "findings": []}
    finally:
        pin_ctx.reset(token)


async def test_get_findings_without_pin_raises() -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await analyze_mod.get_analysis_findings._tool_func()
        assert exc.value.reason == "missing_itinerary_id"
    finally:
        pin_ctx.reset(token)
