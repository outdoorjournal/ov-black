"""Strands event → SSE frame translation.

The entrypoint feeds every dict that ``stream_async`` yields into
:meth:`EventTranslator.translate`. The shapes the browser expects:

- ``{"type": "delta", "text": "..."}`` — streamed tokens
- ``{"type": "card_proposed", "node": {...}}`` — a new node
- ``{"type": "draft_assembled", "edges_created": int}`` — day-by-day ordering
- ``{"type": "node_updated", "node": {...}}`` — advisor adjustment applied
- ``{"type": "itinerary_updated", "itinerary": {...}}`` — trip-level edit (dates)
- ``{"type": "mood", "mood_id": "..."}`` — basecamp ambience shift

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
    "update_trip_timing": "itinerary_updated",
    "set_mood": "mood",
    # Materialised into the reply text as a fenced markdown block rather than a
    # bespoke frame — see ``_timeline_fence``. The emitted frame is a plain
    # ``delta`` so the API's existing text accumulation persists it with the
    # turn and the client renders it via ordinary markdown.
    "propose_timeline": "timeline",
}


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
        return {"type": "card_proposed", "node": output}
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
    return None


class EventTranslator:
    """Stateful Strands event → SSE frame translator.

    Holds a per-turn ``toolUseId → tool_name`` map so a later
    ``ToolResultMessageEvent`` (which only carries ``toolUseId``) can be
    routed to the right SSE frame shape. Construct one per turn.
    """

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}

    def translate(self, event: Any) -> Iterator[dict]:
        """Map one Strands event dict to zero or more SSE frame dicts."""
        if not isinstance(event, dict):
            return

        delta_text = _extract_delta_text(event)
        if delta_text is not None:
            yield {"type": "delta", "text": delta_text}
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
        # First pass: capture toolUse → name mappings (assistant messages).
        for block in content:
            if isinstance(block, dict):
                tu = block.get("toolUse") or block.get("tool_use")
                if isinstance(tu, dict):
                    tuid = tu.get("toolUseId") or tu.get("tool_use_id")
                    name = tu.get("name")
                    if isinstance(tuid, str) and isinstance(name, str):
                        self._tool_names[tuid] = name
        # Second pass: emit frames for any toolResult blocks (user-role
        # messages carrying tool execution results).
        for block in content:
            if isinstance(block, dict):
                tr = block.get("toolResult") or block.get("tool_result")
                if isinstance(tr, dict):
                    yield from self._translate_tool_result_block(tr)

    def _translate_tool_result_block(self, tr: dict) -> Iterator[dict]:
        # Resolve the tool name. Real Strands toolResult blocks have only
        # toolUseId; legacy/test shapes may carry an explicit name.
        name = (
            tr.get("toolName")
            or tr.get("name")
            or tr.get("toolUseName")
            or tr.get("tool_name")
        )
        if not isinstance(name, str):
            tuid = tr.get("toolUseId") or tr.get("tool_use_id")
            if isinstance(tuid, str):
                name = self._tool_names.get(tuid)
        if not isinstance(name, str):
            return
        if name not in _TOOL_FRAME_TYPES:
            return  # Read-only tools — no UI frame.

        # Output may be at content/output/result keys; payload may be a
        # plain dict or Strands' wrapped content-block list.
        raw: Any = tr.get("output")
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
        if frame is not None:
            yield frame


def translate_event(event: Any) -> Iterator[dict]:
    """One-shot stateless translator.

    Real turn streaming should construct an :class:`EventTranslator`
    once and call ``translate`` per event so toolUseId → name
    correlation works across the assistant message and the subsequent
    tool-result message. This free function exists for callers and
    tests that work with self-contained legacy envelopes.
    """
    yield from EventTranslator().translate(event)
