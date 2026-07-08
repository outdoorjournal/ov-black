"""SSE frame parsing — a faithful port of ``apps/web/lib/agentStream.ts``.

The backend emits ``data: <json>\\n\\n`` frames. We parse the same protocol the
browser does (split on ``\\n\\n``, collect ``data:`` lines, JSON-decode, drop
non-JSON / unknown-shape frames) so the harness consumes turns *the same way
the UI does*. Frames are surfaced as lightweight typed objects for ergonomic
rendering and assertions, with the raw dict preserved on each.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The exact set the UI knows (agentStream.ts KNOWN_FRAME_TYPES). Unknown types
# are forwarded by the backend verbatim and surface here as UnknownFrame.
KNOWN_FRAME_TYPES: frozenset[str] = frozenset(
    {
        "first_token",
        "delta",
        "done",
        "error",
        "card",
        "card_proposed",
        "draft_assembled",
        "node_updated",
        "mood",
    }
)


@dataclass(frozen=True, slots=True)
class Frame:
    """Base parsed SSE frame; ``raw`` is the full decoded payload."""

    type: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FirstTokenFrame(Frame):
    ms: int = 0


@dataclass(frozen=True, slots=True)
class DeltaFrame(Frame):
    text: str = ""


@dataclass(frozen=True, slots=True)
class DoneFrame(Frame):
    turn_id: str = ""
    model: str | None = None
    latency_ms: int | None = None
    first_token_ms: int | None = None
    retried: int = 0


@dataclass(frozen=True, slots=True)
class ErrorFrame(Frame):
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CardFrame(Frame):
    """S07 OV-experience proposal: a node persisted before the frame is sent."""

    source: str = ""
    source_id: str = ""
    node_id: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CardProposedFrame(Frame):
    node: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NodeUpdatedFrame(Frame):
    node: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DraftAssembledFrame(Frame):
    edges_created: int = 0


@dataclass(frozen=True, slots=True)
class MoodFrame(Frame):
    mood_id: str = ""


@dataclass(frozen=True, slots=True)
class ToolTraceFrame(Frame):
    """EVAL-1 observability: one tool call/result, emitted by the agent when
    ``EMIT_TOOL_TRACE`` is on. Deliberately NOT in ``KNOWN_FRAME_TYPES`` — the
    browser drops it; only harness consumers (this SDK, the eval runner) see it.
    Carries the tool name + toolUseId + status only, never inputs/outputs.
    """

    tool: str = ""
    phase: str = ""  # "call" | "result"
    tool_use_id: str = ""
    status: str | None = None  # Strands "success"/"error"; None on call frames.


@dataclass(frozen=True, slots=True)
class UnknownFrame(Frame):
    """A JSON frame whose ``type`` the UI does not model — kept, not dropped."""


def _as_int(value: Any, default: int = 0) -> int:
    return int(value) if isinstance(value, (int, float)) else default


def _opt_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def to_frame(payload: dict[str, Any]) -> Frame:
    """Map a decoded JSON payload to its typed Frame."""
    kind = payload.get("type")
    if not isinstance(kind, str):
        return UnknownFrame(type="", raw=payload)
    if kind == "first_token":
        return FirstTokenFrame(type=kind, raw=payload, ms=_as_int(payload.get("ms")))
    if kind == "delta":
        text = payload.get("text")
        return DeltaFrame(type=kind, raw=payload, text=text if isinstance(text, str) else "")
    if kind == "done":
        model = payload.get("model")
        return DoneFrame(
            type=kind,
            raw=payload,
            turn_id=str(payload.get("turn_id", "")),
            model=model if isinstance(model, str) else None,
            latency_ms=_opt_int(payload.get("latency_ms")),
            first_token_ms=_opt_int(payload.get("first_token_ms")),
            retried=_as_int(payload.get("retried")),
        )
    if kind == "error":
        return ErrorFrame(type=kind, raw=payload, reason=str(payload.get("reason", "")))
    if kind == "card":
        snap = payload.get("snapshot")
        return CardFrame(
            type=kind,
            raw=payload,
            source=str(payload.get("source", "")),
            source_id=str(payload.get("source_id", "")),
            node_id=str(payload.get("node_id", "")),
            snapshot=snap if isinstance(snap, dict) else {},
        )
    if kind == "card_proposed":
        node = payload.get("node")
        return CardProposedFrame(
            type=kind, raw=payload, node=node if isinstance(node, dict) else {}
        )
    if kind == "node_updated":
        node = payload.get("node")
        return NodeUpdatedFrame(type=kind, raw=payload, node=node if isinstance(node, dict) else {})
    if kind == "draft_assembled":
        return DraftAssembledFrame(
            type=kind, raw=payload, edges_created=_as_int(payload.get("edges_created"))
        )
    if kind == "mood":
        return MoodFrame(type=kind, raw=payload, mood_id=str(payload.get("mood_id", "")))
    if kind == "tool_trace":
        status = payload.get("status")
        return ToolTraceFrame(
            type=kind,
            raw=payload,
            tool=str(payload.get("tool", "")),
            phase=str(payload.get("phase", "")),
            tool_use_id=str(payload.get("tool_use_id") or ""),
            status=status if isinstance(status, str) else None,
        )
    return UnknownFrame(type=kind, raw=payload)


def parse_frames(buffer: str) -> tuple[list[Frame], str]:
    """Parse complete frames from ``buffer``; return (frames, remaining_buffer).

    Mirrors agentStream.ts ``parseFrames``: split on ``\\n\\n``, join ``data:``
    lines with ``\\n``, JSON-decode, drop non-JSON and non-dict payloads.
    """
    frames: list[Frame] = []
    cursor = 0
    while True:
        delim = buffer.find("\n\n", cursor)
        if delim == -1:
            break
        raw_frame = buffer[cursor:delim]
        cursor = delim + 2

        data_pieces: list[str] = []
        for line in raw_frame.split("\n"):
            if line.startswith("data: "):
                data_pieces.append(line[6:])
            elif line.startswith("data:"):
                data_pieces.append(line[5:])
        if not data_pieces:
            continue

        try:
            parsed = json.loads("\n".join(data_pieces))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        frames.append(to_frame(parsed))

    return frames, buffer[cursor:]
