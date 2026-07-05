"""Per-mode prompt assembly + tool bundle selection."""

from __future__ import annotations

import uuid

from agent.prompts import build_prompt
from agent.schemas import Mode, TurnPayload
from agent.tools import tools_for


def _payload(**overrides) -> TurnPayload:
    base = {
        "system": "VOICE PREAMBLE + Dossier context",
        "input_text": "hi",
        "mode": Mode.onboarding,
        "auth_bearer": "eyJfake",
        "client_id": uuid.uuid4(),
    }
    base.update(overrides)
    return TurnPayload.model_validate(base)


def test_onboarding_prompt_mentions_search_inventory_and_propose_card() -> None:
    prompt = build_prompt(
        mode=Mode.onboarding,
        api_system="VOICE PREAMBLE",
        actor_kind="user",
        itinerary_id_present=False,
    )
    assert "VOICE PREAMBLE" in prompt
    assert "search_inventory" in prompt
    assert "propose_card" in prompt
    assert "Mode: onboarding" in prompt


def test_every_mode_teaches_rendering_affordances() -> None:
    # The RENDERING_NOTE (timeline tool + place-chip token) is appended to every
    # mode's rubric so rich replies work regardless of persona.
    for mode in (Mode.onboarding, Mode.planning, Mode.qa):
        prompt = build_prompt(
            mode=mode,
            api_system="VP",
            actor_kind="user",
            itinerary_id_present=mode is not Mode.onboarding,
        )
        assert "propose_timeline" in prompt, mode
        assert "place:" in prompt, mode


def test_planning_prompt_client_vs_advisor_voice_differ() -> None:
    it_id = uuid.uuid4()
    client_prompt = build_prompt(
        mode=Mode.planning,
        api_system="VP",
        actor_kind="user",
        itinerary_id_present=True,
    )
    advisor_prompt = build_prompt(
        mode=Mode.planning,
        api_system="VP",
        actor_kind="advisor",
        itinerary_id_present=True,
    )
    assert client_prompt != advisor_prompt
    assert "advisor" in advisor_prompt.lower()


def test_planning_without_pin_tells_agent_how_to_bootstrap() -> None:
    prompt = build_prompt(
        mode=Mode.planning,
        api_system="VP",
        actor_kind="user",
        itinerary_id_present=False,
    )
    assert "not yet pinned" in prompt or "list_itineraries" in prompt


def test_qa_prompt_general_vs_pinned() -> None:
    general = build_prompt(
        mode=Mode.qa,
        api_system="VP",
        actor_kind="user",
        itinerary_id_present=False,
    )
    pinned = build_prompt(
        mode=Mode.qa,
        api_system="VP",
        actor_kind="user",
        itinerary_id_present=True,
    )
    assert general != pinned
    assert "list_itineraries" in general
    assert "get_itinerary" in pinned
    # Both QA variants teach the traveler feedback flow (note + alternative).
    assert "add_note" in general and "add_note" in pinned


def test_tool_bundles_are_mode_appropriate() -> None:
    onboarding_names = {t.__name__ for t in tools_for(Mode.onboarding)}
    planning_names = {t.__name__ for t in tools_for(Mode.planning)}
    qa_names = {t.__name__ for t in tools_for(Mode.qa)}

    # Onboarding may propose cards but cannot update node status.
    assert "propose_card" in onboarding_names
    assert "update_node_status" not in onboarding_names

    # The timeline is a pure rendering affordance (no writes) — available in
    # every mode, including read-mostly Q&A.
    assert "propose_timeline" in onboarding_names
    assert "propose_timeline" in planning_names
    assert "propose_timeline" in qa_names

    # Planning has the full write surface, including note + move.
    assert "propose_card" in planning_names
    assert "assemble_draft" in planning_names
    assert "update_node_status" in planning_names
    assert "move_node" in planning_names
    assert "add_note" in planning_names

    # Q&A is read-mostly: a narrow traveler write surface (note / fork / move /
    # request_reconcile) but never the full authoring toolkit.
    assert {"add_note", "fork_itinerary", "move_node", "request_reconcile"} <= qa_names
    assert "propose_card" not in qa_names
    assert "assemble_draft" not in qa_names
    assert "update_node_status" not in qa_names
    assert "search_inventory" not in qa_names
    assert "list_itineraries" in qa_names


def test_turn_payload_rejects_missing_required_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TurnPayload.model_validate(
            {
                "system": "x",
                "mode": "onboarding",
                # missing input_text / auth_bearer / client_id
            }
        )


def test_turn_payload_accepts_null_itinerary_id() -> None:
    payload = _payload(itinerary_id=None)
    assert payload.itinerary_id is None


def test_turn_payload_accepts_empty_auth_bearer_for_summoned_turn() -> None:
    # M006/PS8: an @-mention summon carries no user JWT — it acts only through
    # the agent_token path, so an empty auth_bearer must validate.
    payload = _payload(auth_bearer="")
    assert payload.auth_bearer == ""
