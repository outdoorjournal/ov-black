"""Agent conversation layer — drives turns exactly as the UI does.

OpenAPI does not model the SSE turn stream, so this sits on top of the SDK
transport rather than the generated client (the web makes the same split:
generated client for JSON routes, ``agentStream.ts`` for the stream). A
:class:`Conversation` opens/reuses a session for a client (as traveler or
staff, depending on the JWT the underlying :class:`~ovb.sdk.Ovb` carries) and
streams turns, accumulating the assistant prose and any graph mutations the
agent makes mid-turn — the same frames the mood board reacts to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ovb._generated import models as gm
from ovb.errors import ApiError, TurnError
from ovb.sdk import Ovb
from ovb.sse import (
    CardFrame,
    CardProposedFrame,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    FirstTokenFrame,
    Frame,
    MoodFrame,
    NodeUpdatedFrame,
    ToolTraceFrame,
    parse_frames,
)


async def stream_turn(
    ovb: Ovb, session_id: str, content: str, *, surface: str | None = None
) -> AsyncIterator[Frame]:
    """Stream one turn, yielding typed SSE frames as they arrive.

    ``surface`` names the UI surface sending the turn (``"intake"`` — the
    immersive first-conversation screen — or ``"kickoff"`` — the campaign
    dashboard opener). The API pins the agent's mode from it, exactly as the
    web surfaces do; omit it for ordinary journal/dashboard turns.

    Raises :class:`ApiError` if the endpoint rejects the turn before streaming
    (e.g. 404 session_not_found, 422 bad content) — matching the UI's
    pre-stream JSON error contract.
    """
    body: dict[str, Any] = {"content": content}
    if surface is not None:
        body["surface"] = surface
    async with ovb.transport.stream("POST", f"/sessions/{session_id}/turn", json_body=body) as resp:
        if resp.status_code != 200:
            await resp.aread()
            reason = f"http_{resp.status_code}"
            try:
                payload = resp.json()
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, str):
                    reason = detail
                elif isinstance(detail, list):
                    reason = "validation_error"
            except ValueError:
                pass
            raise ApiError(
                resp.status_code,
                reason,
                method="POST",
                path=f"/sessions/{session_id}/turn",
            )

        buffer = ""
        async for chunk in resp.aiter_text():
            buffer += chunk
            frames, buffer = parse_frames(buffer)
            for frame in frames:
                yield frame
        # Flush any trailing complete frame (terminated by a final \n\n).
        frames, _ = parse_frames(buffer if buffer.endswith("\n\n") else buffer + "\n\n")
        for frame in frames:
            yield frame


@dataclass(slots=True)
class TurnResult:
    """Everything one turn produced — prose plus the graph mutations it made."""

    content: str = ""
    first_token_ms: int | None = None
    done: DoneFrame | None = None
    error: ErrorFrame | None = None
    mood_id: str | None = None
    cards: list[CardFrame] = field(default_factory=list)
    proposed_nodes: list[dict[str, Any]] = field(default_factory=list)
    updated_nodes: list[dict[str, Any]] = field(default_factory=list)
    tool_trace: list[ToolTraceFrame] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)

    @property
    def turn_id(self) -> str | None:
        return self.done.turn_id if self.done else None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def tools_called(self) -> list[str]:
        """Tool names in call order (from ``tool_trace``; empty when the agent
        runs without ``EMIT_TOOL_TRACE`` — callers should treat that as
        "unobserved", not "no tools ran")."""
        names = [f.tool for f in self.tool_trace if f.phase == "call" and f.tool]
        if names:
            return names
        # Older/partial traces may carry results only.
        return [f.tool for f in self.tool_trace if f.phase == "result" and f.tool]


async def run_turn(
    ovb: Ovb,
    session_id: str,
    content: str,
    *,
    surface: str | None = None,
    on_frame: Any = None,
    raise_on_error: bool = False,
) -> TurnResult:
    """Consume a turn stream into a :class:`TurnResult`.

    ``on_frame`` (optional callable) is invoked per frame for live rendering.
    """
    result = TurnResult()
    async for frame in stream_turn(ovb, session_id, content, surface=surface):
        result.frames.append(frame)
        if on_frame is not None:
            on_frame(frame)
        if isinstance(frame, DeltaFrame):
            result.content += frame.text
        elif isinstance(frame, FirstTokenFrame):
            result.first_token_ms = frame.ms
        elif isinstance(frame, DoneFrame):
            result.done = frame
            if frame.first_token_ms is not None:
                result.first_token_ms = frame.first_token_ms
        elif isinstance(frame, ErrorFrame):
            result.error = frame
        elif isinstance(frame, CardFrame):
            result.cards.append(frame)
        elif isinstance(frame, CardProposedFrame):
            result.proposed_nodes.append(frame.node)
        elif isinstance(frame, NodeUpdatedFrame):
            result.updated_nodes.append(frame.node)
        elif isinstance(frame, MoodFrame):
            result.mood_id = frame.mood_id
        elif isinstance(frame, ToolTraceFrame):
            result.tool_trace.append(frame)
    if raise_on_error and result.error is not None:
        raise TurnError(result.error.reason)
    return result


@dataclass(slots=True)
class Conversation:
    """A live session for one client, driven turn by turn like the UI."""

    ovb: Ovb
    client_id: str
    session_id: str
    agentcore_session_id: str
    itinerary_id: str | None = None
    audience: str = "traveler"
    history: list[TurnResult] = field(default_factory=list)

    @classmethod
    async def open(
        cls,
        ovb: Ovb,
        *,
        client_id: str,
        itinerary_id: str | None = None,
        seeded_opener: str | None = None,
        audience: gm.SessionAudience | str | None = None,
    ) -> Conversation:
        """Open or reuse a session (idempotent per client, like the UI).

        ``audience`` selects which conversation this is: ``'traveler'`` (the
        shared client thread, the default) or ``'advisor'`` (the private
        advisor↔AI workspace the traveler never sees — B7). A traveler actor
        is gated to ``'traveler'`` server-side; asking for ``'advisor'`` as a
        traveler 404s (existence-hiding).
        """
        opened = await ovb.open_session(
            client_id=client_id,
            itinerary_id=itinerary_id,
            seeded_opener=seeded_opener,
            audience=audience,
        )
        return cls(
            ovb=ovb,
            client_id=client_id,
            session_id=str(opened.session_id),
            agentcore_session_id=opened.agentcore_session_id,
            itinerary_id=str(opened.itinerary_id) if opened.itinerary_id else None,
            audience=str(opened.audience) if opened.audience else "traveler",
        )

    async def say(
        self,
        content: str,
        *,
        surface: str | None = None,
        on_frame: Any = None,
        raise_on_error: bool = False,
    ) -> TurnResult:
        result = await run_turn(
            self.ovb,
            self.session_id,
            content,
            surface=surface,
            on_frame=on_frame,
            raise_on_error=raise_on_error,
        )
        self.history.append(result)
        # The agent may auto-create + pin an itinerary on the first card.
        if self.itinerary_id is None:
            for node in result.proposed_nodes:
                itin = node.get("itinerary_id")
                if isinstance(itin, str):
                    self.itinerary_id = itin
                    break
        return result
