"""`ovb invoices` — assemble, view, and run the invoice ledger lifecycle (M005)."""

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of

app = typer.Typer(help="Invoices: create, assemble a signed ledger, issue/void.")


@app.command("create")
def create(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    currency: str = typer.Option(..., "--currency", "-c", help="ISO 4217, e.g. USD."),
    label: str = typer.Option("", "--label", "-l", help='e.g. "Deposit".'),
    due_at: str | None = typer.Option(None, "--due-at", help="ISO-8601 due date."),
) -> None:
    """Create a draft invoice over an itinerary (advisor)."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.create_invoice(itinerary_id, label=label, currency=currency, due_at=due_at),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("invoice", res))


@app.command("list")
def list_(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
) -> None:
    """List an itinerary's invoices."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_invoices(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.invoices_table(res))


@app.command("get")
def get(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
) -> None:
    """Show an invoice with its ledger and computed total."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.get_invoice(invoice_id))
    render.emit(state.json_mode, res, lambda: render.invoice_panel(res))


@app.command("add-line")
def add_line(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
    node_id: str | None = typer.Option(
        None, "--node-id", help="Charge a node's cost (omit --amount)."
    ),
    amount: str | None = typer.Option(
        None, "--amount", "-a", help="Signed amount (a discount is negative)."
    ),
    kind: str = typer.Option("charge", "--kind", "-k", help="charge|discount|adjustment|tax|fee."),
    currency: str | None = typer.Option(None, "--currency", "-c", help="Required with --amount."),
    description: str = typer.Option("", "--description", "-d", help="Line description."),
) -> None:
    """Append a line — a manual signed line, or a node-cost charge."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.add_invoice_line(
            invoice_id,
            kind=kind,
            description=description,
            amount=amount,
            currency=currency,
            node_id=node_id,
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("line", res))


@app.command("void-line")
def void_line(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
    line_id: str = typer.Argument(..., help="Line item UUID."),
) -> None:
    """Void a line by appending a reversal entry (advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.void_invoice_line(invoice_id, line_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("reversal", res))


@app.command("remove-line")
def remove_line(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
    line_id: str = typer.Argument(..., help="Line item UUID."),
) -> None:
    """Hard-delete a line (draft-only, advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.remove_invoice_line(invoice_id, line_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("removed", {"ok": True}))


@app.command("issue")
def issue(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
) -> None:
    """Issue a draft invoice — makes it payable (advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.issue_invoice(invoice_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("issued", res))


@app.command("void")
def void(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
) -> None:
    """Void (cancel) an invoice (advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.void_invoice(invoice_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("voided", res))


@app.command("token")
def token(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
) -> None:
    """Mint a gateway client token for the drop-in (owning client or advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.payment_token(invoice_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("payment token", res))


@app.command("pay")
def pay(
    ctx: typer.Context,
    invoice_id: str = typer.Argument(..., help="Invoice UUID."),
    nonce: str = typer.Option(
        "fake-valid-nonce", "--nonce", "-n", help="Payment method nonce (sandbox/fake)."
    ),
) -> None:
    """Pay an issued invoice with a tokenized card nonce (owning client or advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.pay_invoice(invoice_id, payment_method_nonce=nonce))
    render.emit(state.json_mode, res, lambda: render.invoice_panel(res))
