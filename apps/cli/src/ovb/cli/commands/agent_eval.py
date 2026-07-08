"""`ovb agent eval` — run declarative eval scenarios against the LIVE agent.

The scenario runner (EVAL-1) drives real SSE turns through the same loop the
UI uses and scores each turn on invariants: which tools fired (via the
debug-gated ``tool_trace`` frames — the agent must run with
``EMIT_TOOL_TRACE=1``), which frames were emitted, what the graph diff was,
and (optionally) an LLM-judge rubric. See ``ovb.evals`` for the scenario
shape; scenarios load from a JSON file (one object, a list, or
``{"scenarios": [...]}``).

    ovb agent eval scenarios.json --client-id <id> [--itinerary-id <id>] [--judge]
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of
from ovb.errors import OvbError
from ovb.evals import EvalReport, bedrock_judge, run_scenario, scenarios_from_json
from ovb.sdk import Ovb
from ovb.sse import DeltaFrame, Frame, ToolTraceFrame

app = typer.Typer(help="Agent eval harness — scenario runs over the live agent.")


def _live_printer() -> object:
    """Stream deltas + tool fires inline so a long live turn shows progress."""

    def on_frame(frame: Frame) -> None:
        if isinstance(frame, DeltaFrame):
            sys.stdout.write(frame.text)
            sys.stdout.flush()
        elif isinstance(frame, ToolTraceFrame) and frame.phase == "call":
            render.console.print(f"\n  [dim]⚙ {frame.tool}[/dim]")

    return on_frame


_OUTCOME_STYLE = {
    "pass": "[green]pass[/green]",
    "fail": "[red]FAIL[/red]",
    "skip": "[dim]skip[/dim]",
}


def _render_report(report: EvalReport) -> None:
    verdict = "[green]PASSED[/green]" if report.passed else "[red]FAILED[/red]"
    render.console.print(f"\n[bold]{report.scenario}[/bold] — {verdict}")
    for i, turn in enumerate(report.turns, start=1):
        render.console.print(f"  turn {i}: [italic]{turn.say[:80]}[/italic]")
        if turn.tools_called:
            render.console.print(f"    tools: {', '.join(turn.tools_called)}")
        if turn.diff_summary:
            render.console.print(f"    graph: {turn.diff_summary}")
        for check in turn.checks:
            style = _OUTCOME_STYLE.get(check.outcome, check.outcome)
            detail = f" — {check.detail}" if check.detail else ""
            render.console.print(f"    {style} {check.name}{detail}")


@app.command("eval")
def eval_(
    ctx: typer.Context,
    scenario_file: Path = typer.Argument(
        ..., exists=True, readable=True, help="JSON scenario file (see ovb.evals)."
    ),
    client_id: str = typer.Option(..., "--client-id"),
    itinerary_id: str | None = typer.Option(None, "--itinerary-id"),
    judge: bool = typer.Option(
        False, "--judge", help="Score rubric checks with the Bedrock LLM judge."
    ),
    as_role: str | None = typer.Option(None, "--as", help="traveler | staff (default: staff)."),
) -> None:
    """Run every scenario in FILE against the live agent; exit 1 on any failure."""
    state = state_of(ctx)
    try:
        scenarios = scenarios_from_json(scenario_file.read_text())
    except OSError as exc:
        raise OvbError(f"cannot read {scenario_file}: {exc}") from exc
    if not scenarios:
        raise typer.BadParameter(f"{scenario_file} holds no scenarios")

    judge_fn = bedrock_judge if judge else None
    on_frame = None if state.json_mode else _live_printer()

    async def _run(ovb: Ovb) -> list[EvalReport]:
        reports = []
        for scenario in scenarios:
            if not state.json_mode:
                render.console.print(f"\n[bold cyan]▶ {scenario.name}[/bold cyan]")
            reports.append(
                await run_scenario(
                    ovb,
                    scenario,
                    client_id=client_id,
                    itinerary_id=itinerary_id,
                    judge=judge_fn,
                    on_frame=on_frame,
                )
            )
        return reports

    reports = run_op(ctx, _run, role=as_role or "staff")

    if state.json_mode:
        render.print_json(
            {"passed": all(r.passed for r in reports), "reports": [r.to_dict() for r in reports]}
        )
    else:
        for report in reports:
            _render_report(report)
    if not all(r.passed for r in reports):
        raise typer.Exit(1)
