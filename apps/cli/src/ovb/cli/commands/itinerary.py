"""`ovb itinerary` — create, view (as a graph), and run the advisor lifecycle."""

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of

app = typer.Typer(help="Itineraries: create, view as a graph, approve/lock/assemble.")


@app.command("create")
def create(
    ctx: typer.Context,
    title: str = typer.Option("", "--title", "-t", help="Itinerary title."),
    client_id: str | None = typer.Option(None, "--client-id", help="Owning client UUID."),
) -> None:
    """Create a new (draft) itinerary graph."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.create_itinerary(title=title, client_id=client_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("itinerary", res))


@app.command("get")
def get(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
) -> None:
    """Fetch the assembled graph and render it the way the UI canvas reads."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.get_graph(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.graph_tree(res))


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List every itinerary across the advisor's clients."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_advisor_itineraries())
    render.emit(state.json_mode, res, lambda: render.itineraries_table(res))


@app.command("approve-all")
def approve_all(
    ctx: typer.Context, itinerary_id: str = typer.Argument(..., help="Itinerary UUID.")
) -> None:
    """Approve every pending approvable card on the official trip."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.approve_all(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("approved", res))


@app.command("lock")
def lock(
    ctx: typer.Context, itinerary_id: str = typer.Argument(..., help="Itinerary UUID.")
) -> None:
    """Acquire the advisor editor lock (queues agent writes)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.lock(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("locked", res))


@app.command("release")
def release(
    ctx: typer.Context, itinerary_id: str = typer.Argument(..., help="Itinerary UUID.")
) -> None:
    """Release the lock and drain any queued agent writes."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.release(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("released", res))


@app.command("assemble")
def assemble(
    ctx: typer.Context, itinerary_id: str = typer.Argument(..., help="Itinerary UUID.")
) -> None:
    """Assemble the initial draft (follows-edges across days)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.assemble(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.graph_tree(res))
