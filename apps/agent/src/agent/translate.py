"""Strands event → SSE frame translation.

The entrypoint feeds every dict that ``stream_async`` yields into
:meth:`EventTranslator.translate`. The shapes the browser expects:

- ``{"type": "delta", "text": "..."}`` — streamed tokens
- ``{"type": "card_proposed", "node": {...}}`` — a new node
- ``{"type": "node_created", "node": {...}}`` — a persisted node the agent built
  server-side (e.g. a campaign-spine card); the store drops it straight onto the
  canvas, no accept step. One frame per node so a batch reveals card-by-card.
- ``{"type": "draft_assembled", "edges_created": int}`` — day-by-day ordering
- ``{"type": "node_updated", "node": {...}}`` — advisor adjustment applied
- ``{"type": "itinerary_updated", "itinerary": {...}}`` — trip-level edit (dates)
- ``{"type": "mood", "mood_id": "..."}`` — basecamp ambience shift
- ``{"type": "profile_updated", "kind": "..."}`` — onboarding fact captured (kind only)

Not every tool maps to a bespoke frame: ``propose_timeline`` is materialised
into the reply text as a fenced ``ov-timeline`` markdown block emitted as a
plain ``delta`` (see ``_timeline_fence``), so it persists with the turn and
renders through ordinary markdown rather than a dedicated frame type.

Strands does NOT yield a single event with both the tool name and its
output: ``ToolResultEvent`` is non-callback (so ``stream_async`` never
yields it), and the ``ToolResultMessageEvent`` we DO see carries
``toolUseId`` + ``content`` but **no name**. The name lives on the
prior assistant ``ModelMessageEvent``'s ``toolUse`` block, paired by
``toolUseId``. ``EventTranslator`` correlates the two by remembering
``{toolUseId → name}`` for the lifetime of one turn.

Tool returns are wrapped by Strands' ``@tool`` decorator: a dict that
isn't already in ``{status, content}`` form gets serialized into
``content: [{"text": json.dumps(result)}]``. The translator parses
that back into a dict before shaping the SSE frame.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger("agent.translate")


_TOOL_FRAME_TYPES = {
    "propose_card": "card_proposed",
    "propose_flight": "card_proposed",
    # Collection writes surface as cards too — they persist an unscheduled node,
    # which the client files into the wish list (no start_time) rather than the
    # timeline. Same frame, same store add; the rail derives the Collection view.
    "save_to_collection": "card_proposed",
    "save_link_to_collection": "card_proposed",
    "add_collection_note": "card_proposed",
    "assemble_draft": "draft_assembled",
    "update_node_status": "node_updated",
    # Field edits (AGT-1) return the updated node, same shape as a status flip —
    # the browser store adopts it and the card re-renders.
    "update_node_details": "node_updated",
    "update_trip_timing": "itinerary_updated",
    # Naming the adventure (intake) — same frame as a timing edit: the browser
    # re-reads the trip's server-rendered details either way.
    "update_trip_details": "itinerary_updated",
    # Party writes surface so the intake details card can show "who's coming"
    # live. The frame carries a whitelisted subset — never dietary/medical.
    "record_party_member": "party_updated",
    "update_party_member": "party_updated",
    # Onboarding: the basecamp first-touch ledger lights a goal checkmark when
    # the agent captures a profile fact. The frame carries ONLY the fact kind
    # (never the text) — the ledger just needs to know *which* goal landed.
    "record_profile_fact": "profile_updated",
    # The intake hand-off: the immersive surface docks the chat and lands the
    # traveler on the trip dashboard when this frame arrives.
    "complete_intake": "intake_complete",
    "set_mood": "mood",
    # Presentation surfaces (the drawer beside the chat). The tool result is
    # already ``{surface_id, kind, payload}``-shaped; an error result is
    # dropped so the browser never sees a malformed panel.
    "present_route": "surface",
    "present_options": "surface",
    # The reading suggestion rides the same surface envelope (kind="article"):
    # {surface_id, kind, payload} → article flyout beside the chat.
    "suggest_reading": "surface",
    # Materialised into the reply text as a fenced markdown block rather than a
    # bespoke frame — see ``_timeline_fence``. The emitted frame is a plain
    # ``delta`` so the API's existing text accumulation persists it with the
    # turn and the client renders it via ordinary markdown.
    "propose_timeline": "timeline",
}

# Tools that build a BATCH of persisted nodes server-side (the campaign spine).
# They aren't proposals — they're the instantiated trip — so each returned node
# fans out as its own ``node_created`` frame (via ``created_nodes`` on the tool
# result), letting the whole skeleton stream onto the canvas live.
_MULTI_NODE_CREATE_TOOLS = {"assemble_campaign_spine"}


def _timeline_fence(output: dict) -> str | None:
    """Render a ``propose_timeline`` result as an ``ov-timeline`` markdown block.

    The block is wrapped in blank lines so it always parses as its own markdown
    block regardless of surrounding prose, and is JSON-serialised as a single
    unit so it arrives in one delta — the client never sees a half-parsed fence.
    Returns ``None`` for an error/empty result so no block is emitted.
    """
    if "error" in output:
        return None
    days = output.get("days")
    if not isinstance(days, list) or not days:
        return None
    payload: dict[str, Any] = {"days": days}
    caption = output.get("caption")
    if isinstance(caption, str) and caption:
        payload["caption"] = caption
    body = json.dumps(payload, ensure_ascii=False)
    return f"\n\n```ov-timeline\n{body}\n```\n\n"


def _extract_delta_text(event: dict) -> str | None:
    """Pull text from a Strands/Bedrock delta envelope in a version-tolerant way."""
    # Current Strands shape: {"data": "<text>", "delta": {"text": "<text>"}, ...}
    data = event.get("data")
    if isinstance(data, str) and data:
        return data
    # Older Strands shape: delta as a plain string.
    if isinstance(event.get("delta"), str):
        return event["delta"] or None
    # Type-hinted releases.
    if event.get("type") in {"delta", "text_delta"}:
        text = event.get("text")
        if isinstance(text, str):
            return text or None
    # Bedrock Converse raw top-level envelope (very old Strands). The
    # current SDK wraps these in {"event": {...}} AND re-emits a
    # {"data": "..."} frame — we pick the normalized one above to avoid
    # double-emitting, so this path only catches legacy top-level shapes.
    block = event.get("contentBlockDelta") or event.get("content_block_delta")
    if isinstance(block, dict):
        d = block.get("delta")
        if isinstance(d, dict):
            text = d.get("text")
            if isinstance(text, str):
                return text or None
    return None


def _tool_result_payload(raw: Any) -> dict | None:
    """Recover the original tool return dict from a Strands toolResult body.

    A dict already at the top level passes through. A Strands content list
    is searched for the first parseable dict — either a ``{"json": {...}}``
    block (tools that return a Bedrock-shaped result) or a ``{"text": ...}``
    block holding a JSON-encoded dict (the wrap path the ``@tool`` decorator
    takes for plain dict returns).
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, list):
        return None
    for block in raw:
        if not isinstance(block, dict):
            continue
        json_value = block.get("json") or block.get("output")
        if isinstance(json_value, dict):
            return json_value
        text = block.get("text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _frame_for_tool(name: str, output: dict) -> dict | None:
    """Shape a tool's return dict into the frame the browser expects."""
    frame_type = _TOOL_FRAME_TYPES.get(name)
    if frame_type is None:
        return None
    if frame_type == "card_proposed":
        # ``additional_nodes`` is a sibling-node envelope (a round-trip flight
        # splits into outbound + return); it rides the write response, not the
        # card itself, and is fanned out into extra frames by the caller.
        node = {k: v for k, v in output.items() if k != "additional_nodes"}
        return {"type": "card_proposed", "node": node}
    if frame_type == "draft_assembled":
        return {
            "type": "draft_assembled",
            "edges_created": int(
                output.get("edges_created", len(output.get("edges") or []))
            ),
        }
    if frame_type == "node_updated":
        return {"type": "node_updated", "node": output}
    if frame_type == "itinerary_updated":
        return {"type": "itinerary_updated", "itinerary": output}
    if frame_type == "party_updated":
        # Whitelisted subset only: the intake details card needs a name and a
        # relationship, never the member's dietary/medical/notes fields.
        if "error" in output or not isinstance(output.get("id"), str | int):
            return None
        member: dict[str, Any] = {"id": str(output["id"])}
        full_name = output.get("full_name")
        if isinstance(full_name, str):
            member["full_name"] = full_name
        relationship = output.get("relationship_to_primary")
        if isinstance(relationship, str):
            member["relationship_to_primary"] = relationship
        if isinstance(output.get("is_primary"), bool):
            member["is_primary"] = output["is_primary"]
        return {"type": "party_updated", "member": member}
    if frame_type == "profile_updated":
        # Kind only — the traveler-told text never rides this frame (the ledger
        # shows a checkmark, not the fact). Drop an error result on the floor.
        kind = output.get("kind")
        if "error" in output or not isinstance(kind, str):
            return None
        return {"type": "profile_updated", "kind": kind}
    if frame_type == "intake_complete":
        if "error" in output:
            return None
        return {"type": "intake_complete"}
    if frame_type == "mood":
        # An invalid mood_id payload (the tool returned `{"error": ...}`)
        # is dropped on the floor — the browser never sees a malformed
        # mood frame. The error is still observable via tool-result trace.
        mood_id = output.get("mood_id")
        if isinstance(mood_id, str) and "error" not in output:
            return {"type": "mood", "mood_id": mood_id}
        return None
    if frame_type == "timeline":
        fence = _timeline_fence(output)
        if fence is None:
            return None
        return {"type": "delta", "text": fence}
    if frame_type == "surface":
        kind = output.get("kind")
        payload = output.get("payload")
        surface_id = output.get("surface_id")
        if "error" in output or not isinstance(kind, str) or not isinstance(payload, dict):
            return None
        return {
            "type": "surface",
            "surface_id": surface_id if isinstance(surface_id, str) else "",
            "kind": kind,
            "payload": payload,
        }
    return None


class EventTranslator:
    """Stateful Strands event → SSE frame translator.

    Holds a per-turn ``toolUseId → tool_name`` map so a later
    ``ToolResultMessageEvent`` (which only carries ``toolUseId``) can be
    routed to the right SSE frame shape. Construct one per turn.

    ``emit_tool_trace`` (EVAL-1) additionally surfaces that map on the wire:
    a ``tool_trace`` frame per tool call (``phase="call"``) and per tool
    result (``phase="result"``, with the Strands success/error status) for
    **every** tool, including the read-only ones that map to no UI frame.
    The payload is redaction-safe by construction — tool name, toolUseId and
    status only, never inputs or outputs (which can carry Dossier/OSINT
    content). Real browsers drop unknown frame types, so the frame is only
    consumed by harness clients (ovb / the eval runner).

    Independently of the trace flag, every tool call/result ALWAYS emits an
    ``activity`` frame carrying nothing but ``phase`` — no tool name, id,
    status or payload. Even a tool's *name* can disclose private machinery
    to a traveler (``record_dossier_inference``), so the browser-facing
    pulse is anonymous by construction. It serves two consumers: the chat
    surface animates "the concierge is working" during a tool-first
    preamble, and the API's first-token liveness deadline re-arms on any
    upstream event, so long tool work is never mistaken for a dead runtime.
    """

    # Trailing characters that end a clause — after one of these, prose resuming
    # past a tool call starts a fresh paragraph. Includes closing quotes/brackets,
    # the em-dash, and the ellipsis.
    _SENTENCE_END = frozenset(".!?:;—…”’\"')]}")

    def __init__(self, *, emit_tool_trace: bool = False) -> None:
        self._emit_tool_trace = emit_tool_trace
        self._tool_names: dict[str, str] = {}
        # Paragraph-break bookkeeping: a tool call splits the model's narration
        # into two assistant messages whose text the API concatenates verbatim,
        # so "…looks like." and "**Extraterrestrial**…" arrive glued. Track
        # whether a tool ran since the last text and the last char emitted, so
        # resuming prose can re-break itself.
        self._tool_boundary = False
        self._emitted_text = False
        self._last_char = ""

    @staticmethod
    def _separator_after_tool(prev_char: str, next_text: str) -> str:
        """The separator to splice in when prose resumes after a tool ran.

        A paragraph break after a completed clause, a single space mid-sentence
        (so two words never fuse), and nothing when either side already carries
        whitespace.
        """
        next_char = next_text[0] if next_text else ""
        if not prev_char or prev_char in " \n" or next_char in " \n":
            return ""
        if prev_char in EventTranslator._SENTENCE_END:
            return "\n\n"
        return " "

    def _emit_delta(self, text: str) -> Iterator[dict]:
        """Yield a ``delta`` frame, re-breaking prose that resumes after a tool."""
        if not text:
            return
        out = text
        if self._tool_boundary and self._emitted_text:
            sep = self._separator_after_tool(self._last_char, text)
            if sep:
                out = sep + text
        self._tool_boundary = False
        self._emitted_text = True
        self._last_char = text[-1]
        yield {"type": "delta", "text": out}

    def translate(self, event: Any) -> Iterator[dict]:
        """Map one Strands event dict to zero or more SSE frame dicts."""
        if not isinstance(event, dict):
            return

        delta_text = _extract_delta_text(event)
        if delta_text is not None:
            yield from self._emit_delta(delta_text)
            return

        # Reasoning / thinking stream. Any model with thinking enabled (Sonnet 5
        # has it always on; Sonnet 4.6 emits it when thinking is turned on) fans
        # out ``{"reasoning": True, ...}`` frames whose text is INTERNAL — never
        # surfaced to the traveler (``_extract_delta_text`` deliberately returns
        # None for them). But a long think between tool calls is silent on the
        # wire, and the API's first-token liveness watchdog cuts a turn it
        # believes has gone dead — the intermittent ``upstream_unavailable``. So
        # emit an anonymous, content-free pulse: it re-arms that watchdog exactly
        # like a tool-activity frame, without disclosing the thinking. Distinct
        # phase so it never flips the tool-in-flight state; the browser drops the
        # unknown phase, making this a server-side liveness signal only.
        if event.get("reasoning") is True:
            yield {"type": "activity", "phase": "thinking"}
            return

        message = event.get("message")
        if isinstance(message, dict):
            yield from self._translate_message(message)
            return

        # Legacy top-level tool_result envelope (older Strands releases and
        # the synthetic test fixtures). Real Strands ≥ 1.x routes tool
        # results through ``message`` events, handled above.
        tr = event.get("tool_result") or event.get("toolResult")
        if isinstance(tr, dict):
            yield from self._translate_tool_result_block(tr)
            return

        # Reasoning, tool_use streams, model metadata — internal, not
        # surfaced to the browser.
        return

    def _translate_message(self, message: dict) -> Iterator[dict]:
        content = message.get("content")
        if not isinstance(content, list):
            return
        # First pass: capture toolUse → name mappings (assistant messages). A
        # tool call here is a prose boundary — the next text delta re-breaks.
        for block in content:
            if isinstance(block, dict):
                tu = block.get("toolUse") or block.get("tool_use")
                if isinstance(tu, dict):
                    self._tool_boundary = True
                    yield {"type": "activity", "phase": "call"}
                    tuid = tu.get("toolUseId") or tu.get("tool_use_id")
                    name = tu.get("name")
                    if isinstance(tuid, str) and isinstance(name, str):
                        self._tool_names[tuid] = name
                        if self._emit_tool_trace:
                            yield {
                                "type": "tool_trace",
                                "phase": "call",
                                "tool": name,
                                "tool_use_id": tuid,
                            }
        # Second pass: emit frames for any toolResult blocks (user-role
        # messages carrying tool execution results).
        for block in content:
            if isinstance(block, dict):
                tr = block.get("toolResult") or block.get("tool_result")
                if isinstance(tr, dict):
                    yield from self._translate_tool_result_block(tr)

    def _translate_tool_result_block(self, tr: dict) -> Iterator[dict]:
        # A tool result is a prose boundary too (covers the legacy top-level
        # path where no separate assistant toolUse message was seen).
        self._tool_boundary = True
        yield {"type": "activity", "phase": "result"}
        # Resolve the tool name. Real Strands toolResult blocks have only
        # toolUseId; legacy/test shapes may carry an explicit name.
        name = (
            tr.get("toolName")
            or tr.get("name")
            or tr.get("toolUseName")
            or tr.get("tool_name")
        )
        tuid = tr.get("toolUseId") or tr.get("tool_use_id")
        if not isinstance(name, str) and isinstance(tuid, str):
            name = self._tool_names.get(tuid)
        if not isinstance(name, str):
            return
        if self._emit_tool_trace:
            # Redaction-safe by construction: name + id + status, never the
            # result payload (it can carry Dossier/OSINT content).
            status = tr.get("status")
            yield {
                "type": "tool_trace",
                "phase": "result",
                "tool": name,
                "tool_use_id": tuid if isinstance(tuid, str) else None,
                "status": status if isinstance(status, str) else None,
            }
        # Batch node builders (campaign spine): fan each created node out as its
        # own ``node_created`` frame so the skeleton streams onto the canvas
        # live. These tools aren't in ``_TOOL_FRAME_TYPES`` (no single frame).
        if name in _MULTI_NODE_CREATE_TOOLS:
            raw = tr.get("output") or tr.get("content") or tr.get("result")
            output = _tool_result_payload(raw)
            if output is not None:
                created = output.get("created_nodes")
                if isinstance(created, list):
                    for node in created:
                        if isinstance(node, dict):
                            yield {"type": "node_created", "node": node}
            return

        if name not in _TOOL_FRAME_TYPES:
            return  # Read-only tools — no UI frame.

        # Output may be at content/output/result keys; payload may be a
        # plain dict or Strands' wrapped content-block list.
        raw = tr.get("output")
        if raw is None:
            raw = tr.get("content")
        if raw is None:
            raw = tr.get("result")
        output = _tool_result_payload(raw)
        if output is None:
            logger.warning(
                "agent.translate.unparseable_tool_output",
                extra={"tool": name},
            )
            return
        frame = _frame_for_tool(name, output)
        if frame is None:
            return
        if frame.get("type") == "delta":
            # A tool materialised into reply text (propose_timeline's fence) —
            # route it through the delta path so the fence's own blank lines feed
            # the paragraph-break bookkeeping and never double up.
            yield from self._emit_delta(str(frame.get("text", "")))
        else:
            yield frame
            # A from-inventory write can create sibling nodes alongside the
            # primary (a round-trip flight → outbound + return). Each rides
            # ``additional_nodes`` on the response; fan every one out into its
            # own card_proposed frame so the graph renders all legs, not just
            # the first.
            if frame.get("type") == "card_proposed":
                extras = output.get("additional_nodes")
                if isinstance(extras, list):
                    for extra in extras:
                        if isinstance(extra, dict):
                            node = {k: v for k, v in extra.items() if k != "additional_nodes"}
                            yield {"type": "card_proposed", "node": node}


def translate_event(event: Any) -> Iterator[dict]:
    """One-shot stateless translator.

    Real turn streaming should construct an :class:`EventTranslator`
    once and call ``translate`` per event so toolUseId → name
    correlation works across the assistant message and the subsequent
    tool-result message. This free function exists for callers and
    tests that work with self-contained legacy envelopes.
    """
    yield from EventTranslator().translate(event)
