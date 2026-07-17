"""``propose_flight`` and its physical-feasibility guard.

Offline (no backend): monkeypatch the ``post_json`` / ``get_json`` / ``delete_json``
the ``proposals`` module imported and drive the tool's underlying coroutine
(``_tool_func``). Covers the regression where a flight arriving after the plan's
first item was placed anyway — the guard must roll it back and raise.

Phase 5 (doc/itin-time.md): the analysis itself lives in the API's kernel —
the graph read carries ``findings`` and the guard only reacts to
block-severity flight findings that touch the just-created nodes. These tests
therefore feed findings, not raw nodes; the finding computation is covered by
``apps/api/tests/test_kernel_analysis.py`` / ``test_kernel_phase5.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import proposals as proposals_mod


def _pin(itinerary_id: str = "it-1") -> dict[str, Any]:
    return {
        "client_id": "client-9",
        "itinerary_id": itinerary_id,
        "actor_kind": "user",
        "audience": "traveler",
    }


def _flight_node(node_id: str) -> dict:
    return {"id": node_id, "type": "flight", "title": "DTW → SKG"}


def _block_finding(*node_ids: str, message: str = "arrives after the first item") -> dict:
    return {
        "code": "flight_infeasible",
        "severity": "block",
        "message": message,
        "node_ids": list(node_ids),
    }


def _wire(
    monkeypatch: pytest.MonkeyPatch, *, created: dict, findings: list[dict]
) -> dict[str, list]:
    """Stub the backend: from-inventory returns ``created``; the graph read
    returns the kernel findings the guard consults."""
    calls: dict[str, list] = {"post": [], "get": [], "delete": []}

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls["post"].append((path, json))
        return created

    async def _get(path: str, *, params: dict | None = None) -> Any:
        calls["get"].append(path)
        return {"nodes": [], "findings": findings}

    async def _delete(path: str) -> Any:
        calls["delete"].append(path)
        return None

    monkeypatch.setattr(proposals_mod, "post_json", _post)
    monkeypatch.setattr(proposals_mod, "get_json", _get)
    monkeypatch.setattr(proposals_mod, "delete_json", _delete)
    return calls


async def test_blocking_finding_rolls_back_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    late = _flight_node("f-out")
    calls = _wire(monkeypatch, created=late, findings=[_block_finding("f-out", "exp-1")])
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as excinfo:
            await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-late")
    finally:
        pin_ctx.reset(token)
    assert "flight_schedule_conflict" in excinfo.value.reason
    assert "arrives after the first item" in excinfo.value.reason
    # The impossible leg was deleted, not left on the plan.
    assert calls["delete"] == ["/itinerary/it-1/nodes/f-out"]


async def test_roundtrip_rolls_back_both_legs(monkeypatch: pytest.MonkeyPatch) -> None:
    # A round-trip offer lands as outbound + return; a block on EITHER leg
    # rolls back the pair (they are one bookable item).
    created = {**_flight_node("f-out"), "additional_nodes": [_flight_node("f-ret")]}
    calls = _wire(monkeypatch, created=created, findings=[_block_finding("f-ret")])
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError):
            await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-rt")
    finally:
        pin_ctx.reset(token)
    assert set(calls["delete"]) == {
        "/itinerary/it-1/nodes/f-out",
        "/itinerary/it-1/nodes/f-ret",
    }


async def test_feasible_flight_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _flight_node("f-out")
    calls = _wire(monkeypatch, created=good, findings=[])
    token = pin_ctx.set(_pin())
    try:
        result = await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-ok")
    finally:
        pin_ctx.reset(token)
    assert result["id"] == "f-out"
    assert calls["delete"] == []


async def test_warn_and_unrelated_findings_do_not_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tight-but-possible margins warn (advisor's call, not a rollback), and a
    # block about some OTHER node must not delete this proposal.
    good = _flight_node("f-out")
    calls = _wire(
        monkeypatch,
        created=good,
        findings=[
            {
                "code": "flight_tight",
                "severity": "warn",
                "message": "only 90 min before the first item",
                "node_ids": ["f-out"],
            },
            _block_finding("f-other"),
            {
                "code": "overlap",
                "severity": "warn",
                "message": "overlaps dinner",
                "node_ids": ["f-out", "meal-1"],
            },
        ],
    )
    token = pin_ctx.set(_pin())
    try:
        result = await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-ok")
    finally:
        pin_ctx.reset(token)
    assert result["id"] == "f-out"
    assert calls["delete"] == []


async def test_guard_fails_open_when_graph_read_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # A guard bug must never swallow a real, successful proposal.
    late = _flight_node("f-out")

    async def _post(path: str, *, json: dict | None = None) -> Any:
        return late

    async def _get(path: str, *, params: dict | None = None) -> Any:
        raise BackendError(status=500, reason="boom")

    async def _delete(path: str) -> Any:  # pragma: no cover - must not be reached
        raise AssertionError("should not roll back when the guard itself failed")

    monkeypatch.setattr(proposals_mod, "post_json", _post)
    monkeypatch.setattr(proposals_mod, "get_json", _get)
    monkeypatch.setattr(proposals_mod, "delete_json", _delete)
    token = pin_ctx.set(_pin())
    try:
        result = await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-late")
    finally:
        pin_ctx.reset(token)
    assert result["id"] == "f-out"
