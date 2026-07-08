"""`ovb chat` — talk to the agent about an itinerary, as a traveler or staff.

Drives the SSE turn loop exactly as the UI does (open/reuse a session, stream
``delta``/``card``/``done`` frames). The identity (``--as traveler`` vs
``--as staff``) is just which JWT we present — apps/api derives actor_kind from
the Supabase role.
"""

import asyncio
import sys
from typing import Any

import typer

from ovb.agent import Conversation, TurnResult, run_turn
from ovb.cli import render
from ovb.cli._run import run_op, state_of
from ovb.config import Profile
from ovb.sdk import Ovb
from ovb.sse import CardFrame, CardProposedFrame, DeltaFrame, Frame, MoodFrame, ToolTraceFrame

app = typer.Typer(help="Chat with the agent (as traveler or staff) over a session.")


def _turn_json(result: TurnResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "turn_id": result.turn_id,
        "content": result.content,
        "first_token_ms": result.first_token_ms,
        "mood_id": result.mood_id,
        "cards": [render.to_jsonable(c) for c in result.cards],
        "proposed_nodes": result.proposed_nodes,
        "updated_nodes": result.updated_nodes,
        "tools_called": result.tools_called,
        "error": result.error.reason if result.error else None,
    }


def _live_printer() -> Any:
    """Stream delta text to stdout as it arrives; flag cards/mood inline."""

    def on_frame(frame: Frame) -> None:
        if isinstance(frame, DeltaFrame):
            sys.stdout.write(frame.text)
            sys.stdout.flush()
        elif isinstance(frame, CardFrame):
            render.console.print(f"\n  [dim]· card {frame.source}/{frame.source_id}[/dim]")
        elif isinstance(frame, CardProposedFrame):
            title = frame.node.get("title", "") if isinstance(frame.node, dict) else ""
            render.console.print(f"\n  [dim]· proposed node {title}[/dim]")
        elif isinstance(frame, MoodFrame):
            render.console.print(f"\n  [dim]· mood → {frame.mood_id}[/dim]")
        elif isinstance(frame, ToolTraceFrame) and frame.phase == "call":
            # Only present when the agent runs with EMIT_TOOL_TRACE=1.
            render.console.print(f"\n  [dim]⚙ {frame.tool}[/dim]")

    return on_frame


def _footer(result: TurnResult) -> None:
    bits = []
    if result.first_token_ms is not None:
        bits.append(f"first token {result.first_token_ms}ms")
    if result.cards or result.proposed_nodes:
        bits.append(f"{len(result.cards) + len(result.proposed_nodes)} card(s)")
    if result.mood_id:
        bits.append(f"mood {result.mood_id}")
    if result.error:
        render.console.print(f"\n[red]— turn error: {result.error.reason}[/red]")
    elif bits:
        render.console.print(f"\n[dim]— {', '.join(bits)}[/dim]")
    else:
        render.console.print("")


@app.command("open")
def open_(
    ctx: typer.Context,
    client_id: str = typer.Option(..., "--client-id"),
    itinerary_id: str | None = typer.Option(None, "--itinerary-id"),
    seeded_opener: str | None = typer.Option(None, "--seeded-opener"),
    as_role: str | None = typer.Option(None, "--as", help="traveler | staff."),
) -> None:
    """Open or reuse a session for a client (idempotent)."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.open_session(
            client_id=client_id, itinerary_id=itinerary_id, seeded_opener=seeded_opener
        ),
        role=as_role,
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("session", res))


@app.command("say")
def say(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="What to say to the agent."),
    session_id: str = typer.Option(..., "--session-id"),
    as_role: str | None = typer.Option(None, "--as", help="traveler | staff."),
) -> None:
    """Stream a single turn on an existing session."""
    state = state_of(ctx)
    on_frame = None if state.json_mode else _live_printer()
    result = run_op(
        ctx,
        lambda ovb: run_turn(ovb, session_id, message, on_frame=on_frame),
        role=as_role,
    )
    if state.json_mode:
        render.print_json(_turn_json(result))
    else:
        _footer(result)


@app.command("turns")
def turns(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
) -> None:
    """List every turn recorded on a session."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_turns(session_id))
    render.emit(state.json_mode, res, lambda: render.turns_table(res))


@app.command("repl")
def repl(
    ctx: typer.Context,
    client_id: str = typer.Option(..., "--client-id"),
    itinerary_id: str | None = typer.Option(None, "--itinerary-id"),
    as_role: str | None = typer.Option(None, "--as", help="traveler | staff."),
) -> None:
    """Interactive conversation. Type messages; Ctrl-D or /exit to quit."""
    state = state_of(ctx)
    if state.json_mode:
        raise typer.BadParameter("--json is not supported in the interactive repl")
    role = as_role or state.role
    profile: Profile = state.profile

    async def _session() -> None:
        async with Ovb.for_identity(profile, email=state.email, role=role) as ovb:
            convo = await Conversation.open(ovb, client_id=client_id, itinerary_id=itinerary_id)
            who = (
                "traveler" if (role or profile.default_role) in {"traveler", "client"} else "staff"
            )
            render.console.print(
                f"[bold]session[/bold] {convo.session_id}  "
                f"[dim](as {who}; itinerary {convo.itinerary_id or '—'})[/dim]\n"
            )
            on_frame = _live_printer()
            while True:
                try:
                    line = await asyncio.to_thread(input, "› ")
                except EOFError:
                    break
                line = line.strip()
                if not line:
                    continue
                if line in {"/exit", "/quit"}:
                    break
                render.console.print("[dim]…[/dim]", end="\r")
                result = await convo.say(line, on_frame=on_frame)
                _footer(result)

    try:
        asyncio.run(_session())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    except Exception as exc:  # noqa: BLE001 - surface any error cleanly
        render.err_console.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(1) from exc
