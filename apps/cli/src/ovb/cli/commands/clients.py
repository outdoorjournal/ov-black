"""`ovb clients` and `ovb facts` — advisor-side client + fact management."""

from typing import Any

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of

app = typer.Typer(help="Clients: create, inspect, list sessions.")
facts_app = typer.Typer(help="Facts: add to a client's dossier / profile / osint tier.")


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List the advisor's clients, newest first."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_clients())
    render.emit(state.json_mode, res, lambda: render.clients_table(res.clients))


@app.command("create")
def create(
    ctx: typer.Context,
    full_name: str = typer.Option(..., "--name", help="Client full name."),
    email: str = typer.Option(..., "--email", help="Client email (welcome link target)."),
    contact_preference: str = typer.Option("email", "--contact-pref"),
    party_notes: str = typer.Option("", "--party-notes"),
    children_ages: str | None = typer.Option(None, "--children-ages", help="Comma-separated ints."),
    net_worth: int | None = typer.Option(None, "--net-worth"),
) -> None:
    """Create a client + dossier and email a code-free welcome sign-in link (atomic)."""
    state = state_of(ctx)
    typed: dict[str, Any] = {
        "contact_preference": contact_preference,
        "travel_party_notes": party_notes,
    }
    if children_ages:
        typed["children_ages"] = [int(x) for x in children_ages.split(",") if x.strip()]
    if net_worth is not None:
        typed["estimated_net_worth_usd"] = net_worth
    payload = {"full_name": full_name, "email": email, "dossier": {"typed": typed}}
    res = run_op(ctx, lambda ovb: ovb.create_client(payload))
    render.emit(state.json_mode, res, lambda: render.kv_panel("client created", res))


@app.command("get")
def get(
    ctx: typer.Context,
    client_id: str = typer.Argument(...),
    include_redacted: bool = typer.Option(False, "--include-redacted"),
) -> None:
    """Show a client + dossier + active facts (advisor view)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.get_client(client_id, include_redacted=include_redacted))
    render.emit(state.json_mode, res, lambda: render.kv_panel("client", res))


@app.command("sessions")
def sessions(ctx: typer.Context, client_id: str = typer.Argument(...)) -> None:
    """List the agent sessions for one client."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_client_sessions(client_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("sessions", res))


@app.command("resend-welcome")
def resend_welcome(ctx: typer.Context, client_id: str = typer.Argument(...)) -> None:
    """Re-send the welcome sign-in link to a pending client (nudge)."""
    state = state_of(ctx)
    run_op(ctx, lambda ovb: ovb.resend_welcome(client_id))
    render.emit(state.json_mode, {"ok": True}, lambda: "welcome link re-sent")


@facts_app.command("add")
def fact_add(
    ctx: typer.Context,
    client_id: str = typer.Argument(...),
    tier: str = typer.Option(..., "--tier", help="dossier | profile | osint."),
    kind: str = typer.Option(..., "--kind"),
    text: str = typer.Option(..., "--text"),
    source_kind: str | None = typer.Option(None, "--source-kind"),
) -> None:
    """Add a fact to a client's dossier/profile/osint tier (advisor-attributed)."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.add_fact(
            client_id, tier=tier, kind=kind, text=text, source_kind=source_kind
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel(f"{tier} fact", res))
