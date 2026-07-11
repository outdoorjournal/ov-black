"""translate_event — Strands event dict → SSE frame dict."""

from __future__ import annotations

import json

from collections.abc import Iterable

from agent.translate import EventTranslator, translate_event


def _ui(frames: Iterable[dict]) -> list[dict]:
    """The UI-frame view: drop the unconditional anonymous ``activity`` pulse."""
    return [f for f in frames if f.get("type") != "activity"]


def _one(event: dict) -> dict | None:
    frames = _ui(translate_event(event))
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


def test_tool_result_update_node_details_maps_to_node_updated() -> None:
    # AGT-1: a field edit returns the updated node, same frame as a status flip
    # — the browser store adopts it and the card re-renders.
    event = {
        "tool_result": {
            "name": "update_node_details",
            "output": {"id": "n1", "title": "Omakase", "cost_amount": "400.00"},
        }
    }
    assert _one(event) == {
        "type": "node_updated",
        "node": {"id": "n1", "title": "Omakase", "cost_amount": "400.00"},
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
    assert _ui(translate_event(event)) == []


def test_prose_resumes_with_paragraph_break_after_tool() -> None:
    """A narration line before a tool call and the result text after it must not
    run together — the resumed prose re-breaks into its own paragraph."""
    t = EventTranslator()
    assert list(t.translate({"delta": "Let me pull up the itinerary."})) == [
        {"type": "delta", "text": "Let me pull up the itinerary."}
    ]
    # A read-only tool ran (no UI frame) — but it IS a prose boundary.
    list(t.translate(_assistant_tool_use_event("tu-r", "get_traveler_context")))
    list(t.translate(_tool_result_message_event("tu-r", {"profile_facts": []})))
    # The next chunk gets a leading paragraph break (prev char was a period).
    assert list(t.translate({"delta": "**Extraterrestrial** is a meal card"})) == [
        {"type": "delta", "text": "\n\n**Extraterrestrial** is a meal card"}
    ]


def test_midsentence_resume_after_tool_uses_a_single_space() -> None:
    """If the model paused mid-sentence for a tool, don't fuse the two words."""
    t = EventTranslator()
    list(t.translate({"delta": "Let me check the price"}))
    list(t.translate(_assistant_tool_use_event("tu-p", "search_inventory")))
    assert list(t.translate({"delta": "of that suite for you."})) == [
        {"type": "delta", "text": " of that suite for you."}
    ]


def test_no_break_when_whitespace_already_present() -> None:
    t = EventTranslator()
    list(t.translate({"delta": "One moment.\n"}))
    list(t.translate(_assistant_tool_use_event("tu-w", "get_traveler_context")))
    # prev char is a newline → nothing spliced in.
    assert list(t.translate({"delta": "Here's what I found."})) == [
        {"type": "delta", "text": "Here's what I found."}
    ]


def test_first_text_after_tool_has_no_leading_break() -> None:
    """No prose was emitted before the tool → don't lead the reply with a break."""
    t = EventTranslator()
    list(t.translate(_assistant_tool_use_event("tu-f", "get_traveler_context")))
    list(t.translate(_tool_result_message_event("tu-f", {"profile_facts": []})))
    assert list(t.translate({"delta": "Welcome back, Chris."})) == [
        {"type": "delta", "text": "Welcome back, Chris."}
    ]


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
    frames = _ui(
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
    frames = _ui(
        translator.translate(
            _tool_result_message_event("tu-2", {"error": "unknown_mood", "mood_id": "bogus"})
        )
    )
    assert frames == []


def test_propose_card_paired_messages_emits_card_proposed() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-3", "propose_card")))
    frames = _ui(
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
    frames = _ui(
        translator.translate(
            _tool_result_message_event("tu-4", {"edges": [{"id": "e1"}, {"id": "e2"}]})
        )
    )
    assert frames == [{"type": "draft_assembled", "edges_created": 2}]


def test_update_node_status_paired_messages_emits_node_updated() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-5", "update_node_status")))
    frames = _ui(
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
    frames = _ui(
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
    frames = _ui(translator.translate(_tool_result_message_event("tu-tl", payload)))

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
    frames = _ui(
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
    frames = _ui(
        translator.translate(_tool_result_message_event("tu-orphan", {"mood_id": "alpine"}))
    )
    assert frames == []


def test_read_only_tool_paired_messages_emits_no_frame() -> None:
    translator = EventTranslator()
    list(translator.translate(_assistant_tool_use_event("tu-6", "get_traveler_context")))
    frames = _ui(
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
    frames = _ui(translator.translate(event))
    assert frames == [{"type": "mood", "mood_id": "ember"}]


# ── tool_trace (EVAL-1) ──────────────────────────────────────────────────────


def test_tool_trace_off_by_default() -> None:
    translator = EventTranslator()
    frames = list(translator.translate(_assistant_tool_use_event("tu-8", "search_inventory")))
    frames += list(translator.translate(_tool_result_message_event("tu-8", {"items": []})))
    assert all(f.get("type") != "tool_trace" for f in frames)


def test_tool_trace_emits_call_and_result_for_read_only_tool() -> None:
    # Read-only tools map to no UI frame, but the trace still surfaces them —
    # that's the whole point of the eval harness observability.
    translator = EventTranslator(emit_tool_trace=True)
    call_frames = list(
        translator.translate(_assistant_tool_use_event("tu-9", "get_itinerary"))
    )
    assert call_frames == [
        {"type": "activity", "phase": "call"},
        {"type": "tool_trace", "phase": "call", "tool": "get_itinerary", "tool_use_id": "tu-9"},
    ]
    result_frames = list(
        translator.translate(_tool_result_message_event("tu-9", {"nodes": []}))
    )
    assert result_frames == [
        {"type": "activity", "phase": "result"},
        {
            "type": "tool_trace",
            "phase": "result",
            "tool": "get_itinerary",
            "tool_use_id": "tu-9",
            "status": "success",
        },
    ]


def test_tool_trace_precedes_ui_frame_and_carries_no_payload() -> None:
    translator = EventTranslator(emit_tool_trace=True)
    list(translator.translate(_assistant_tool_use_event("tu-10", "set_mood")))
    frames = list(
        translator.translate(_tool_result_message_event("tu-10", {"mood_id": "ember"}))
    )
    assert [f["type"] for f in frames] == ["activity", "tool_trace", "mood"]
    trace = frames[1]
    # Redaction: the trace never carries the tool's input or output.
    assert set(trace) == {"type", "phase", "tool", "tool_use_id", "status"}


def test_tool_trace_result_without_prior_tool_use_stays_silent() -> None:
    # Unresolvable name → no trace (nothing meaningful to report) and no crash.
    # The anonymous activity pulse still fires — a tool result DID happen.
    translator = EventTranslator(emit_tool_trace=True)
    frames = list(translator.translate(_tool_result_message_event("tu-11", {"x": 1})))
    assert frames == [{"type": "activity", "phase": "result"}]


# ── activity (anonymous tool pulse) ──────────────────────────────────────────


def test_activity_pulse_always_on() -> None:
    # Emitted with NO trace flag: the browser-facing "concierge is working"
    # signal must exist in every environment, not just eval runs.
    translator = EventTranslator()
    call_frames = list(
        translator.translate(_assistant_tool_use_event("tu-12", "get_traveler_context"))
    )
    assert call_frames == [{"type": "activity", "phase": "call"}]
    result_frames = list(
        translator.translate(_tool_result_message_event("tu-12", {"profile_facts": []}))
    )
    assert result_frames == [{"type": "activity", "phase": "result"}]


def test_activity_pulse_never_identifies_the_tool() -> None:
    # Redaction: even a tool NAME can disclose private machinery to a traveler
    # (record_dossier_inference). The pulse carries type + phase and nothing else.
    translator = EventTranslator()
    frames = list(
        translator.translate(_assistant_tool_use_event("tu-13", "record_dossier_inference"))
    )
    frames += list(translator.translate(_tool_result_message_event("tu-13", {"ok": True})))
    activity = [f for f in frames if f.get("type") == "activity"]
    assert len(activity) == 2
    for frame in activity:
        assert set(frame) == {"type", "phase"}


# ── Intake-surface frames (update_trip_details / party / complete_intake) ────


def test_update_trip_details_result_becomes_itinerary_updated() -> None:
    t = EventTranslator()
    list(t.translate(_assistant_tool_use_event("t1", "update_trip_details")))
    frames = _ui(
        t.translate(
            _tool_result_message_event(
                "t1", {"id": "abc", "title": "Dolomites by First Light"}
            )
        )
    )
    assert frames == [
        {
            "type": "itinerary_updated",
            "itinerary": {"id": "abc", "title": "Dolomites by First Light"},
        }
    ]


def test_party_member_result_becomes_whitelisted_party_updated() -> None:
    t = EventTranslator()
    list(t.translate(_assistant_tool_use_event("t1", "record_party_member")))
    frames = _ui(
        t.translate(
            _tool_result_message_event(
                "t1",
                {
                    "id": "pm-1",
                    "full_name": "Quinn",
                    "relationship_to_primary": "daughter",
                    "is_primary": False,
                    # Private-ish fields that must NOT ride the frame:
                    "dietary": "shellfish allergy",
                    "medical": "asthma",
                    "notes": "secret",
                },
            )
        )
    )
    assert len(frames) == 1
    frame = frames[0]
    assert frame["type"] == "party_updated"
    assert frame["member"] == {
        "id": "pm-1",
        "full_name": "Quinn",
        "relationship_to_primary": "daughter",
        "is_primary": False,
    }
    blob = json.dumps(frame)
    assert "shellfish" not in blob and "asthma" not in blob and "secret" not in blob


def test_complete_intake_result_becomes_intake_complete() -> None:
    t = EventTranslator()
    list(t.translate(_assistant_tool_use_event("t1", "complete_intake")))
    frames = _ui(t.translate(_tool_result_message_event("t1", {"completed": True})))
    assert frames == [{"type": "intake_complete"}]


def test_complete_intake_error_result_emits_nothing() -> None:
    t = EventTranslator()
    list(t.translate(_assistant_tool_use_event("t1", "complete_intake")))
    frames = _ui(t.translate(_tool_result_message_event("t1", {"error": "boom"})))
    assert frames == []
