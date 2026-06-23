"""`ovb analyze` and `ovb fill` — feasibility runs and gap-filling."""

import asyncio
import time

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of
from ovb.sdk import Ovb

app = typer.Typer(help="Analyze: run feasibility checks and read findings.")
fill_app = typer.Typer(help="Fill: rank feasible inventory for a gap.")

_TERMINAL = {"completed", "failed", "cancelled"}


@app.command("start")
def start(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    depth: str = typer.Option("standard", "--depth", help="shallow | standard | deep."),
    force: bool = typer.Option(False, "--force", help="Bypass the cache-hit reuse."),
    wait: bool = typer.Option(False, "--wait", help="Poll until terminal, then show findings."),
    timeout: float = typer.Option(30.0, "--timeout"),
) -> None:
    """Queue an analysis (optionally wait for it and print findings)."""
    state = state_of(ctx)

    async def _go(ovb: Ovb) -> object:
        created = await ovb.start_analysis(itinerary_id, depth=depth, force_rerun=force)
        if not wait:
            return created
        deadline = time.monotonic() + timeout
        analysis_id = str(created.analysis_id)
        while True:
            detail = await ovb.get_analysis(itinerary_id, analysis_id)
            if str(detail.status) in _TERMINAL or time.monotonic() >= deadline:
                return detail
            await asyncio.sleep(0.5)

    res = run_op(ctx, _go)
    if wait:
        render.emit(state.json_mode, res, lambda: render.findings_table(res.findings))  # type: ignore[attr-defined]
    else:
        render.emit(state.json_mode, res, lambda: render.kv_panel("analysis queued", res))


@app.command("list")
def list_(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    limit: int | None = typer.Option(None, "--limit"),
) -> None:
    """List recent analysis runs."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_analyses(itinerary_id, limit=limit))
    render.emit(state.json_mode, res, lambda: render.analyses_table(res))


@app.command("get")
def get(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    analysis_id: str = typer.Argument(...),
) -> None:
    """Show one analysis run and its findings."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.get_analysis(itinerary_id, analysis_id))
    render.emit(state.json_mode, res, lambda: render.findings_table(res.findings))


@app.command("cancel")
def cancel(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    analysis_id: str = typer.Argument(...),
) -> None:
    """Cancel a not-yet-terminal analysis run."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.cancel_analysis(itinerary_id, analysis_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("cancelled", res))


@fill_app.command("run")
def fill_run(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    start: str = typer.Option(..., "--start", help="Gap start (ISO 8601)."),
    end: str = typer.Option(..., "--end", help="Gap end (ISO 8601)."),
    party_id: str | None = typer.Option(None, "--party-id"),
    analysis_id: str | None = typer.Option(None, "--analysis-id"),
    kind: list[str] = typer.Option([], "--kind", help="Desired node kinds."),
    min_score: float | None = typer.Option(None, "--min-score"),
    max_proposals: int | None = typer.Option(None, "--max-proposals"),
) -> None:
    """Rank feasible inventory candidates for a gap."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.fill(
            itinerary_id,
            gap_start=start,
            gap_end=end,
            party_id=party_id,
            analysis_id=analysis_id,
            desired_kinds=kind or None,
            min_score=min_score,
            max_proposals=max_proposals,
        ),
    )
    render.emit(state.json_mode, res, lambda: render.fill_table(res))
