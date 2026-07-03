"""translate_event — Strands event dict → SSE frame dict."""

from __future__ import annotations

import json

from agent.translate import EventTranslator, translate_event


def _one(event: dict) -> dict | None:
    frames = list(translate_event(event))
    return frames[0] if frames else None


def _assistant_tool_use_event(tool_use_id: str, name: str, input_data: dict | None = None) -> dict:
    """Build a Strands ``ModelMessageEvent``-shaped dict for a tool invocation."""
    return {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "toolUseId": tool_use_id,
                        "name": name,
                        "input": input_data or {},
                    }
                }
            ],
        }
    }


def _tool_result_message_event(tool_use_id: str, payload: dict) -> dict:
    """Build a Strands ``ToolResultMessageEvent``-shaped dict.

    Strands' ``@tool`` decorator wraps a plain dict return as
    ``content: [{"text": json.dumps(result)}]`` plus
    ``status: "success"``. Mirror that here.
    """
    return {
        "message": {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "status": "success",
                        "content": [{"text": json.dumps(payload)}],
                    }
                }
            ],
        }
    }


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


def test_tool_result_update_trip_timing_maps_to_itinerary_updated() -> None:
    event = {
        "tool_result": {
            "name": "update_trip_timing",
            "output": {
                "id": "it-1",
                "timing_kind": "exact",
                "date_start": "2026-08-10",
                "date_end": "2026-08-18",
            },
        }
    }
    assert _one(event) == {
        "type": "itinerary_updated",
        "itinerary": {
            "id": "it-1",
            "timing_kind": "exact",
            "date_start": "2026-08-10",
            "date_end": "2026-08-18",
        },
    }


def test_tool_result_read_only_tool_has_no_ui_frame() -> None:
    # get_traveler_context is a read — no SSE frame for the browser.
    event = {"tool_result": {"name": "get_traveler_context", "output": {"profile_facts": []}}}
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


# ── Realistic Strands shapes (paired ModelMessageEvent → ToolResultMessageEvent)
# Strands' real ``ToolResultEvent`` is non-callback, so the only tool
# result data the entrypoint sees is the message-shaped event above.
# Its ``toolResult`` block carries ``toolUseId`` but NO ``name`` — the
# translator correlates by toolUseId with a prior assistant ``toolUse``
# block. These tests exercise that correlation across two events using
# a shared ``EventTranslator`` instance.


def test_set_mood_paired_messages_emits_mood_frame() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-1", "set_mood", {"mood_id": "kyoto-zen"})))
    frames = list(
        translator.translate(
            _tool_result_message_event(
                "tu-1", {"mood_id": "kyoto-zen", "description": "Kyoto stillness."}
            )
        )
    )
    assert frames == [{"type": "mood", "mood_id": "kyoto-zen"}]


def test_set_mood_unknown_id_payload_drops_frame() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-2", "set_mood", {"mood_id": "bogus"})))
    frames = list(
        translator.translate(
            _tool_result_message_event("tu-2", {"error": "unknown_mood", "mood_id": "bogus"})
        )
    )
    assert frames == []


def test_propose_card_paired_messages_emits_card_proposed() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-3", "propose_card")))
    frames = list(
        translator.translate(
            _tool_result_message_event("tu-3", {"id": "node-1", "title": "Dolomites trek"})
        )
    )
    assert frames == [
        {"type": "card_proposed", "node": {"id": "node-1", "title": "Dolomites trek"}}
    ]


def test_assemble_draft_paired_messages_counts_edges() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-4", "assemble_draft")))
    frames = list(
        translator.translate(
            _tool_result_message_event("tu-4", {"edges": [{"id": "e1"}, {"id": "e2"}]})
        )
    )
    assert frames == [{"type": "draft_assembled", "edges_created": 2}]


def test_update_node_status_paired_messages_emits_node_updated() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-5", "update_node_status")))
    frames = list(
        translator.translate(
            _tool_result_message_event("tu-5", {"id": "node-2", "status": "approved"})
        )
    )
    assert frames == [
        {"type": "node_updated", "node": {"id": "node-2", "status": "approved"}}
    ]


def test_update_trip_timing_paired_messages_emits_itinerary_updated() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-8", "update_trip_timing")))
    frames = list(
        translator.translate(
            _tool_result_message_event(
                "tu-8",
                {"id": "it-9", "timing_kind": "window", "duration_nights": 7},
            )
        )
    )
    assert frames == [
        {
            "type": "itinerary_updated",
            "itinerary": {
                "id": "it-9",
                "timing_kind": "window",
                "duration_nights": 7,
            },
        }
    ]


def test_propose_timeline_materializes_ov_timeline_delta() -> None:
    # propose_timeline has no bespoke frame: it renders into the reply text as a
    # fenced ov-timeline block, emitted as a plain delta so the API's text
    # accumulation persists it with the turn.
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-tl", "propose_timeline")))
    payload = {
        "caption": "The shape of the week",
        "days": [
            {"label": "Day 1", "title": "Arrive Fiskardo", "detail": "embark, settle"},
            {"label": "Days 2–3", "title": "North toward Lefkada"},
        ],
    }
    frames = list(translator.translate(_tool_result_message_event("tu-tl", payload)))

    assert len(frames) == 1
    frame = frames[0]
    assert frame["type"] == "delta"
    text = frame["text"]
    # Fenced as its own markdown block, arriving as one atomic delta.
    assert text.startswith("\n\n```ov-timeline\n")
    assert text.endswith("\n```\n\n")
    body = text.split("```ov-timeline\n", 1)[1].rsplit("\n```", 1)[0]
    parsed = json.loads(body)
    assert parsed["caption"] == "The shape of the week"
    assert [d["title"] for d in parsed["days"]] == [
        "Arrive Fiskardo",
        "North toward Lefkada",
    ]


def test_propose_timeline_error_payload_drops_block() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-tlx", "propose_timeline")))
    frames = list(
        translator.translate(
            _tool_result_message_event("tu-tlx", {"error": "invalid_timeline"})
        )
    )
    assert frames == []


def test_tool_result_without_prior_tool_use_is_dropped() -> None:
    # A toolResult arriving with no preceding assistant toolUse block
    # has no name to correlate with, so it cannot be routed to a frame.
    # This is a defensive case — it should never happen in practice.
    translator = EventTranslator()
    frames = list(
        translator.translate(_tool_result_message_event("tu-orphan", {"mood_id": "alpine"}))
    )
    assert frames == []


def test_read_only_tool_paired_messages_emits_no_frame() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-6", "get_traveler_context")))
    frames = list(
        translator.translate(_tool_result_message_event("tu-6", {"profile_facts": []}))
    )
    assert frames == []


def test_translator_correlates_when_tool_use_and_result_share_one_message() -> None:
    # If a single message ever carries both a toolUse and the matching
    # toolResult (e.g. the model emits both inline), the first pass
    # captures the name before the second pass routes the result.
    translator = EventTranslator()
    event = {
        "message": {
            "content": [
                {"toolUse": {"toolUseId": "tu-7", "name": "set_mood", "input": {}}},
                {
                    "toolResult": {
                        "toolUseId": "tu-7",
                        "status": "success",
                        "content": [{"text": json.dumps({"mood_id": "ember"})}],
                    }
                },
            ]
        }
    }
    frames = list(translator.translate(event))
    assert frames == [{"type": "mood", "mood_id": "ember"}]
