"""translate_event — Strands event dict → SSE frame dict."""

from __future__ import annotations

from agent.translate import translate_event


def _one(event: dict) -> dict | None:
    frames = list(translate_event(event))
    return frames[0] if frames else None


def test_delta_with_strands_native_shape() -> None:
    assert _one({"delta": "hello"}) == {"type": "delta", "text": "hello"}


def test_delta_with_type_text_delta_shape() -> None:
    assert _one({"type": "text_delta", "text": "world"}) == {
        "type": "delta",
        "text": "world",
    }


def test_delta_with_bedrock_content_block_delta() -> None:
    assert _one(
        {"contentBlockDelta": {"delta": {"text": "bedrock chunk"}}}
    ) == {"type": "delta", "text": "bedrock chunk"}


def test_empty_delta_is_dropped() -> None:
    assert _one({"delta": ""}) is None


def test_tool_result_propose_card_maps_to_card_proposed() -> None:
    event = {"tool_result": {"name": "propose_card", "output": {"id": "n1", "title": "Dolomites trek"}}}
    assert _one(event) == {
        "type": "card_proposed",
        "node": {"id": "n1", "title": "Dolomites trek"},
    }


def test_tool_result_assemble_draft_counts_edges_via_list() -> None:
    event = {
        "tool_result": {
            "name": "assemble_draft",
            "output": {"edges": [{"id": "e1"}, {"id": "e2"}]},
        }
    }
    assert _one(event) == {"type": "draft_assembled", "edges_created": 2}


def test_tool_result_assemble_draft_honors_explicit_count() -> None:
    event = {
        "tool_result": {
            "name": "assemble_draft",
            "output": {"edges_created": 7, "edges": []},
        }
    }
    assert _one(event) == {"type": "draft_assembled", "edges_created": 7}


def test_tool_result_update_node_status_maps_to_node_updated() -> None:
    event = {
        "tool_result": {
            "name": "update_node_status",
            "output": {"id": "n1", "status": "approved"},
        }
    }
    assert _one(event) == {
        "type": "node_updated",
        "node": {"id": "n1", "status": "approved"},
    }


def test_tool_result_read_only_tool_has_no_ui_frame() -> None:
    # get_voodoo_doll is a read — no SSE frame for the browser.
    event = {"tool_result": {"name": "get_voodoo_doll", "output": {"passions": []}}}
    assert list(translate_event(event)) == []


def test_unknown_event_shape_is_swallowed() -> None:
    assert list(translate_event({"random": "value"})) == []


def test_non_dict_event_is_safe() -> None:
    # Strands has been known to yield strings or None for some internal states.
    assert list(translate_event("not a dict")) == []  # type: ignore[arg-type]


def test_bedrock_converse_tool_result_nested_form() -> None:
    event = {
        "message": {
            "content": [
                {
                    "toolResult": {
                        "toolName": "propose_card",
                        "output": {"id": "abc"},
                    }
                }
            ]
        }
    }
    assert _one(event) == {"type": "card_proposed", "node": {"id": "abc"}}
