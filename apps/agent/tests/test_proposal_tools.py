"""``propose_flight`` and its physical-feasibility guard.

Offline (no backend): monkeypatch the ``post_json`` / ``get_json`` / ``delete_json``
the ``proposals`` module imported and drive the tool's underlying coroutine
(``_tool_func``). Covers the regression where a flight arriving after the plan's
first item was placed anyway — the guard must now roll it back and raise.
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


_OLYMPUS = {"lat": 40.0885, "lng": 22.3489}
_DTW = {"lat": 42.2143, "lng": -83.3544}
_SKG = {"lat": 40.5201, "lng": 22.9713}

_FIRST_ITEM = {
    "id": "exp-1",
    "type": "experience",
    "title": "Trip to Mount Olympus",
    "starts_at": "2026-08-14T15:00:00+03:00",
    "duration_minutes": 8640,
    "metadata": {"location": _OLYMPUS},
}


def _flight_node(node_id: str, depart: str, arrive: str) -> dict:
    return {
        "id": node_id,
        "type": "flight",
        "title": "DTW → SKG",
        "starts_at": depart,
        "metadata": {
            "depart_at": depart,
            "arrive_at": arrive,
            "from_location": _DTW,
            "to_location": _SKG,
        },
    }


def _wire(
    monkeypatch: pytest.MonkeyPatch, *, created: dict, graph_nodes: list[dict]
) -> dict[str, list]:
    """Stub the backend: from-inventory returns ``created``; get returns the graph."""
    calls: dict[str, list] = {"post": [], "get": [], "delete": []}

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls["post"].append((path, json))
        return created

    async def _get(path: str, *, params: dict | None = None) -> Any:
        calls["get"].append(path)
        return {"nodes": graph_nodes}

    async def _delete(path: str) -> Any:
        calls["delete"].append(path)
        return None

    monkeypatch.setattr(proposals_mod, "post_json", _post)
    monkeypatch.setattr(proposals_mod, "get_json", _get)
    monkeypatch.setattr(proposals_mod, "delete_json", _delete)
    return calls


async def test_late_outbound_is_rolled_back_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    late = _flight_node("f-out", "2026-08-14T10:03:00-04:00", "2026-08-15T04:34:00+03:00")
    calls = _wire(monkeypatch, created=late, graph_nodes=[_FIRST_ITEM, late])
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as excinfo:
            await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-late")
    finally:
        pin_ctx.reset(token)
    assert "flight_schedule_conflict" in excinfo.value.reason
    # The impossible leg was deleted, not left on the plan.
    assert calls["delete"] == ["/itinerary/it-1/nodes/f-out"]


async def test_roundtrip_rolls_back_both_legs(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _flight_node("f-out", "2026-08-14T10:03:00-04:00", "2026-08-15T04:34:00+03:00")
    ret = {
        **_flight_node("f-ret", "2026-08-28T20:54:00+03:00", "2026-08-29T01:25:00-04:00"),
        "title": "SKG → DTW",
    }
    ret["metadata"]["from_location"] = _SKG
    ret["metadata"]["to_location"] = _DTW
    created = {**out, "additional_nodes": [ret]}
    calls = _wire(monkeypatch, created=created, graph_nodes=[_FIRST_ITEM, out, ret])
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


async def test_feasible_outbound_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _flight_node("f-out", "2026-08-13T10:03:00-04:00", "2026-08-14T08:00:00+03:00")
    calls = _wire(monkeypatch, created=good, graph_nodes=[_FIRST_ITEM, good])
    token = pin_ctx.set(_pin())
    try:
        result = await proposals_mod.propose_flight._tool_func(source="duffel", source_id="off-ok")
    finally:
        pin_ctx.reset(token)
    assert result["id"] == "f-out"
    assert calls["delete"] == []


async def test_guard_fails_open_when_graph_read_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # A guard bug must never swallow a real, successful proposal.
    late = _flight_node("f-out", "2026-08-14T10:03:00-04:00", "2026-08-15T04:34:00+03:00")

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
