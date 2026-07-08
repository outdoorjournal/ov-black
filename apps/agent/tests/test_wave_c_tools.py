"""Wave C tools — field edits, money reads, and the advisor-thread escalation.

Offline (no backend): monkeypatch the HTTP helpers each tool module imported,
drive the underlying coroutine (``_tool_func``), and assert the request built
+ the guard behavior. Mirrors ``test_analyze_tools.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.backend import BackendError, pin_ctx
from agent.tools import money as money_mod
from agent.tools import mutations as mutations_mod
from agent.tools import thread as thread_mod


def _pin(itinerary_id: str | None = "it-1") -> dict[str, Any]:
    return {
        "client_id": "client-9",
        "itinerary_id": itinerary_id,
        "actor_kind": "advisor",
        "audience": "advisor",
    }


# ── update_node_details (AGT-1) ──────────────────────────────────────────────


async def test_update_details_patches_title_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _patch(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "n-1", "title": "Omakase", "cost_amount": "400.00"}

    monkeypatch.setattr(mutations_mod, "patch_json", _patch)
    token = pin_ctx.set(_pin())
    try:
        out = await mutations_mod.update_node_details._tool_func(
            node_id="n-1",
            title="Omakase",
            cost_amount="400.00",
            cost_currency="USD",
            cost_kind="total",
        )
        path, body = calls[-1]
        assert path == "/itinerary/it-1/nodes/n-1"
        assert body == {
            "title": "Omakase",
            "cost_amount": "400.00",
            "cost_currency": "USD",
            "cost_kind": "total",
        }
        assert out["id"] == "n-1"
    finally:
        pin_ctx.reset(token)


async def test_update_details_merges_metadata_for_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """description/confirmation land via a read-merge-write on metadata —
    the PATCH replaces metadata wholesale, so existing keys must survive."""
    patches: list[tuple[str, Any]] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        return {
            "nodes": [
                {
                    "id": "n-1",
                    "metadata": {"start_time": "2026-09-24T19:00:00+09:00", "snapshot": {"k": 1}},
                }
            ]
        }

    async def _patch(path: str, *, json: dict | None = None) -> Any:
        patches.append((path, json))
        return {"id": "n-1"}

    monkeypatch.setattr(mutations_mod, "get_json", _get)
    monkeypatch.setattr(mutations_mod, "patch_json", _patch)
    token = pin_ctx.set(_pin())
    try:
        await mutations_mod.update_node_details._tool_func(
            node_id="n-1",
            description="Counter seats at the chef's bar.",
            confirmation_number="PNR123",
        )
        _, body = patches[-1]
        assert body == {
            "metadata": {
                "start_time": "2026-09-24T19:00:00+09:00",
                "snapshot": {"k": 1},
                "description": "Counter seats at the chef's bar.",
                "confirmation_number": "PNR123",
            }
        }
    finally:
        pin_ctx.reset(token)


async def test_update_details_refuses_half_cost_pair() -> None:
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as exc:
            await mutations_mod.update_node_details._tool_func(
                node_id="n-1", cost_amount="400.00"
            )
        assert exc.value.reason == "cost_pair_required"
    finally:
        pin_ctx.reset(token)


async def test_update_details_refuses_empty_edit() -> None:
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as exc:
            await mutations_mod.update_node_details._tool_func(node_id="n-1")
        assert exc.value.reason == "nothing_to_update"
    finally:
        pin_ctx.reset(token)


async def test_update_details_without_pin_raises() -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await mutations_mod.update_node_details._tool_func(node_id="n-1", title="X")
        assert exc.value.reason == "missing_itinerary_id"
    finally:
        pin_ctx.reset(token)


async def test_update_details_unknown_node_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(path: str, *, params: dict | None = None) -> Any:
        return {"nodes": []}

    monkeypatch.setattr(mutations_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        with pytest.raises(BackendError) as exc:
            await mutations_mod.update_node_details._tool_func(
                node_id="n-missing", description="x"
            )
        assert exc.value.reason == "not_found"
    finally:
        pin_ctx.reset(token)


# ── money reads (AGT-3) ──────────────────────────────────────────────────────


async def test_get_billing_state_reads_billing_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append(path)
        return {"rows": [], "unbilled_nodes": [], "invoices": []}

    monkeypatch.setattr(money_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        out = await money_mod.get_billing_state._tool_func()
        assert seen == ["/itinerary/it-1/billing"]
        assert out == {"rows": [], "unbilled_nodes": [], "invoices": []}
    finally:
        pin_ctx.reset(token)


async def test_get_booking_state_reads_booking_state_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def _get(path: str, *, params: dict | None = None) -> Any:
        seen.append(path)
        return {"rows": []}

    monkeypatch.setattr(money_mod, "get_json", _get)
    token = pin_ctx.set(_pin())
    try:
        out = await money_mod.get_booking_state._tool_func()
        assert seen == ["/itinerary/it-1/booking-state"]
        assert out == {"rows": []}
    finally:
        pin_ctx.reset(token)


@pytest.mark.parametrize("tool_name", ["get_billing_state", "get_booking_state"])
async def test_money_reads_without_pin_raise(tool_name: str) -> None:
    token = pin_ctx.set(_pin(itinerary_id=None))
    try:
        with pytest.raises(BackendError) as exc:
            await getattr(money_mod, tool_name)._tool_func()
        assert exc.value.reason == "missing_itinerary_id"
    finally:
        pin_ctx.reset(token)


# ── post_thread_message (AGT-4) ──────────────────────────────────────────────


async def test_post_thread_message_posts_agent_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _post(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "m-1", "thread_id": "t-1", "author_kind": "artemis"}

    monkeypatch.setattr(thread_mod, "agent_post_json", _post)
    out = await thread_mod.post_thread_message._tool_func(
        content="Client asks about a private chef evening in Kyoto."
    )
    assert calls == [
        (
            "/agent/thread-message",
            {"content": "Client asks about a private chef evening in Kyoto."},
        )
    ]
    assert out["author_kind"] == "artemis"
