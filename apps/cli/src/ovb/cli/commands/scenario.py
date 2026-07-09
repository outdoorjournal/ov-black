"""`ovb scenario` — run built-in end-to-end flows that double as smoke checks.

These exercise the same Harness the pytest e2e suite uses, so a manual smoke and
an automated test are the same scenario expressed two ways.
"""

import asyncio

import typer

from ovb.agent import Conversation
from ovb.cli import render
from ovb.cli._run import state_of
from ovb.errors import OvbError
from ovb.invariants import assert_no_violations, graph_integrity
from ovb.scenario import Harness

app = typer.Typer(help="Built-in end-to-end scenarios (smoke checks).")


@app.command("smoke")
def smoke(
    ctx: typer.Context,
    client_id: str | None = typer.Option(
        None, "--client-id", help="Client to chat with; defaults to the first one."
    ),
    message: str = typer.Option("Hello — tell me what you can help with.", "--message"),
) -> None:
    """Advisor-side smoke: health → pick client → chat one turn → assert state."""
    state = state_of(ctx)

    async def _go() -> dict[str, object]:
        async with Harness(profile=state.profile) as harness:
            advisor = harness.advisor()
            await advisor.health()
            harness.record("health_ok")

            cid = client_id
            if cid is None:
                clients = (await advisor.list_clients()).clients
                if not clients:
                    raise OvbError("no clients exist; pass --client-id or create one first")
                cid = str(clients[0].id)
            harness.client_id = cid
            harness.record("client_selected", client_id=cid)

            convo = await Conversation.open(advisor, client_id=cid)
            before = len(await advisor.list_turns(convo.session_id))
            result = await convo.say(message)
            after = await advisor.list_turns(convo.session_id)
            harness.record(
                "turn_done",
                turn_id=result.turn_id,
                content_len=len(result.content),
                turns_before=before,
                turns_after=len(after),
            )

            checks: list[str] = []
            assert result.ok, f"turn errored: {result.error.reason if result.error else '?'}"
            checks.append("turn.ok")
            assert len(after) >= before + 1, "no new turn persisted"
            checks.append("turn.persisted")

            if convo.itinerary_id:
                snap = await harness.snapshot(advisor, convo.itinerary_id)
                assert_no_violations(graph_integrity(snap.graph))
                checks.append("graph.integrity")

            return {
                "ok": True,
                "client_id": cid,
                "session_id": convo.session_id,
                "itinerary_id": convo.itinerary_id,
                "assistant_preview": result.content[:160],
                "checks_passed": checks,
                "transcript": [s.label for s in harness.transcript],
            }

    try:
        out = asyncio.run(_go())
    except (AssertionError, OvbError) as exc:
        if state.json_mode:
            render.print_json({"ok": False, "error": str(exc)})
        else:
            render.err_console.print(f"[bold red]smoke failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    if state.json_mode:
        render.print_json(out)
    else:
        render.console.print(render.kv_panel("scenario smoke ✓", out))
