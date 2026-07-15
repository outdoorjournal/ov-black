"""Party-member tools — reconcile-not-duplicate, never invent a birthday.

Offline (no backend): we monkeypatch the ``agent_post_json`` / ``agent_patch_json``
the ``traveler`` module imported, drive each tool's underlying coroutine
(``_tool_func``), and assert the request body it builds. These pin the two
behaviours behind the "the agent made a second Quinn" bug: (1) an existing
member is patched by id, and (2) an absent ``date_of_birth`` is never sent.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent.schemas import Mode
from agent.tools import tools_for
from agent.tools import traveler as traveler_mod


def _names(mode: Mode) -> set[str]:
    return {t.tool_name for t in tools_for(mode)}


def test_onboarding_and_planning_expose_update_party_member() -> None:
    for mode in (Mode.onboarding, Mode.planning):
        names = _names(mode)
        # Both the create and the update path are on offer so the agent can
        # reconcile instead of being forced to duplicate.
        assert {"record_party_member", "update_party_member"} <= names
    # Q&A stays read-mostly: neither party write tool is in that bundle.
    assert "update_party_member" not in _names(Mode.qa)
    assert "record_party_member" not in _names(Mode.qa)


async def test_update_party_member_patches_only_set_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def _patch(path: str, *, json: dict | None = None) -> Any:
        calls.append((path, json))
        return {"id": "m-1", "full_name": "Quinn"}

    monkeypatch.setattr(traveler_mod, "agent_patch_json", _patch)

    await traveler_mod.update_party_member._tool_func(member_id="m-1", full_name="Quinn")

    assert calls == [("/agent/party-members/m-1", {"full_name": "Quinn"})]
    # Only the field the traveller gave is sent — no invented birthday, no
    # clobbering the member's other columns with nulls.
    _, body = calls[0]
    assert body is not None
    assert "date_of_birth" not in body
    assert set(body) == {"full_name"}


async def test_record_party_member_omits_absent_date_of_birth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _post(path: str, *, json: dict | None = None) -> Any:
        captured["path"] = path
        captured["body"] = json
        return {"id": "m-2", "full_name": "Quinn"}

    monkeypatch.setattr(traveler_mod, "agent_post_json", _post)

    # No date_of_birth passed → the tool must not send one (the model has to
    # supply it explicitly; it can never leak an estimate through a default).
    await traveler_mod.record_party_member._tool_func(full_name="Quinn", relationship="son")

    assert captured["path"] == "/agent/party-members"
    assert "date_of_birth" not in captured["body"]
    assert captured["body"]["full_name"] == "Quinn"
    assert captured["body"]["relationship_to_primary"] == "son"


def test_record_travel_logistics_on_gathering_bundles() -> None:
    # The learn-your-airport tool rides with the other gathering writes wherever
    # the traveller might volunteer where they fly from — not on read-mostly Q&A.
    for mode in (Mode.intake, Mode.onboarding, Mode.planning):
        assert "record_travel_logistics" in _names(mode)
    assert "record_travel_logistics" not in _names(Mode.qa)


async def test_record_travel_logistics_sends_only_learned_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _patch(path: str, *, json: dict | None = None) -> Any:
        captured["path"] = path
        captured["body"] = json
        return {"home_airport": "ASE", "skipped": []}

    monkeypatch.setattr(traveler_mod, "agent_patch_json", _patch)

    # Only the home airport was learned this turn — address/currency are omitted,
    # and confirm_overwrite defaults to False so an existing value is never clobbered.
    await traveler_mod.record_travel_logistics._tool_func(home_airport="ASE")

    assert captured["path"] == "/agent/logistics"
    body = captured["body"]
    assert body["home_airport"] == "ASE"
    assert body["confirm_overwrite"] is False
    assert "home_address" not in body
    assert "preferred_currency" not in body
