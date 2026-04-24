"""Strands event → SSE frame translation.

The entrypoint yields dicts the AgentCore runtime serializes as
``data: <json>\\n\\n`` frames. FastAPI's ``stream_turn`` forwards each
frame verbatim to the browser. Three shapes the browser expects:

- ``{"type": "delta", "text": "..."}`` — streamed tokens
- ``{"type": "card_proposed", "node": {...}}`` — a new node
- ``{"type": "draft_assembled", "edges_created": int}`` — day-by-day ordering landed
- ``{"type": "node_updated", "node": {...}}`` — advisor adjustment applied

``translate_event`` is a pure function over the event dict Strands
yields from ``stream_async``. The precise event shape evolves with the
Strands SDK; we dispatch defensively on known keys and swallow
unknowns. Text deltas land with slightly different envelopes in
different SDK versions (``delta``, ``data``, or nested inside a
``content_block_delta`` envelope) — the helper normalizes them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger("agent.translate")


_TOOL_FRAME_TYPES = {
    "propose_card": "card_proposed",
    "assemble_draft": "draft_assembled",
    "update_node_status": "node_updated",
}


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


def _extract_tool_result(event: dict) -> tuple[str, Any] | None:
    """Return ``(tool_name, result)`` for a tool-result event, else None."""
    # Strands' own shape.
    tr = event.get("tool_result") or event.get("toolResult")
    if isinstance(tr, dict):
        name = tr.get("name") or tr.get("toolUseName") or tr.get("tool_name")
        output = tr.get("output") or tr.get("content") or tr.get("result")
        if isinstance(name, str) and output is not None:
            return name, output
    # Nested form sometimes emitted by Bedrock Converse passthrough.
    message = event.get("message")
    if isinstance(message, dict):
        for block in message.get("content") or []:
            if isinstance(block, dict):
                inner = block.get("toolResult") or block.get("tool_result")
                if isinstance(inner, dict):
                    name = inner.get("toolName") or inner.get("name")
                    output = inner.get("output") or inner.get("content")
                    if isinstance(name, str) and output is not None:
                        return name, output
    return None


def translate_event(event: dict) -> Iterator[dict]:
    """Map one Strands event dict to zero or more SSE frame dicts."""
    if not isinstance(event, dict):
        return

    delta_text = _extract_delta_text(event)
    if delta_text is not None:
        yield {"type": "delta", "text": delta_text}
        return

    tool = _extract_tool_result(event)
    if tool is not None:
        name, output = tool
        frame_type = _TOOL_FRAME_TYPES.get(name)
        if frame_type is None:
            return  # Read-only tools — no UI frame.
        frame = _tool_result_to_frame(frame_type, output)
        if frame is not None:
            yield frame
        return

    # Everything else (reasoning, tool_use in progress, model metadata)
    # is internal to the agent turn. Do not surface to the browser.
    return


def _tool_result_to_frame(frame_type: str, output: Any) -> dict | None:
    """Shape a tool's return value into the frame the browser expects."""
    # Tool output may arrive as a dict, or as a list of content blocks
    # (Bedrock Converse tool-result format). Normalize first.
    if isinstance(output, list):
        for block in output:
            if isinstance(block, dict):
                json_value = block.get("json") or block.get("output")
                if isinstance(json_value, dict):
                    output = json_value
                    break
        else:
            logger.warning("agent.translate.unparseable_tool_output", extra={"frame": frame_type})
            return None

    if not isinstance(output, dict):
        return None

    if frame_type == "card_proposed":
        return {"type": "card_proposed", "node": output}
    if frame_type == "draft_assembled":
        return {
            "type": "draft_assembled",
            "edges_created": int(output.get("edges_created", len(output.get("edges") or []))),
        }
    if frame_type == "node_updated":
        return {"type": "node_updated", "node": output}
    return None
