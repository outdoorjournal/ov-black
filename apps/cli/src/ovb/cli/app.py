"""ovb — the CLI entrypoint. Global options resolve a target profile + identity,
then dispatch to AWS-style command groups.

    ovb [--profile P] [--api-url U] [--as ROLE] [--email E] [--json] <group> <cmd>

``--json`` makes every command emit machine-readable JSON (for an agent driving
the tool); without it, output is rich-rendered for a human operator.
"""

import typer

from ovb import __version__
from ovb.cli._run import CliState
from ovb.cli.commands import (
    admin,
    analyze,
    bookings,
    chat,
    clients,
    graph,
    inventory,
    invoices,
    itinerary,
    scenario,
)
from ovb.config import resolve_profile

app = typer.Typer(
    name="ovb",
    help="Operator CLI + e2e harness for the OV Black stack.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,  # never spill secrets into a traceback
)


@app.callback()
def _root(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Target profile (local | staging | …)."
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Override the profile's base URL."),
    as_role: str | None = typer.Option(
        None, "--as", "--role", help="Act as traveler/client or staff/advisor."
    ),
    email: str | None = typer.Option(None, "--email", help="Identity email (for JWT minting)."),
    json_: bool = typer.Option(False, "--json", help="Emit JSON instead of rich output."),
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    if version:
        typer.echo(f"ovb {__version__}")
        raise typer.Exit(0)
    ctx.obj = CliState(
        profile=resolve_profile(profile, api_url=api_url),
        role=as_role,
        email=email,
        json_mode=json_,
    )


app.add_typer(itinerary.app, name="itinerary")
app.add_typer(invoices.app, name="invoices")
app.add_typer(bookings.app, name="bookings")
app.add_typer(graph.node_app, name="node")
app.add_typer(graph.edge_app, name="edge")
app.add_typer(inventory.app, name="inventory")
app.add_typer(analyze.app, name="analyze")
app.add_typer(analyze.fill_app, name="fill")
app.add_typer(clients.app, name="clients")
app.add_typer(clients.facts_app, name="facts")
app.add_typer(chat.app, name="chat")
app.add_typer(scenario.app, name="scenario")
app.add_typer(admin.configure_app, name="configure")
app.add_typer(admin.auth_app, name="auth")
app.add_typer(admin.me_app, name="me")
admin.register_top_level(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
