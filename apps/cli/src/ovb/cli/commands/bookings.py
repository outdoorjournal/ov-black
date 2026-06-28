"""`ovb bookings` — the money gate + booking workflow (M005/I3).

Re-price a held offer, book an approved node against a covering paid invoice
line, record a supplier confirmation #, and read the reconciliation invariant.
"""

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of

app = typer.Typer(help="Bookings: re-price offers, book the money gate, confirm, reconcile.")


@app.command("refresh-offer")
def refresh_offer(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
) -> None:
    """Re-price a node's held offer — live provider or snapshot (advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.refresh_offer(itinerary_id, node_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("offer", res))


@app.command("offers")
def offers(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
) -> None:
    """List a node's offer history (newest first)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.list_offers(itinerary_id, node_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("offers", {"count": len(res)}))


@app.command("book")
def book(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
    override_unpaid: bool = typer.Option(
        False, "--override-unpaid", help="Book on a merely issued line (D-PAY override, logged)."
    ),
) -> None:
    """Book an approved node — the money gate requires a covering paid line (advisor)."""
    state = state_of(ctx)
    res = run_op(
        ctx, lambda ovb: ovb.book_node(itinerary_id, node_id, override_unpaid=override_unpaid)
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("booked", res))


@app.command("confirm")
def confirm(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
    ref: str = typer.Option(..., "--ref", "-r", help="Supplier confirmation # / PNR."),
    terms: str | None = typer.Option(None, "--terms", help="Change/cancel terms."),
) -> None:
    """Record a supplier confirmation # → booked becomes confirmed (advisor)."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.record_confirmation(
            itinerary_id, node_id, supplier_ref=ref, change_cancel_terms=terms
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("confirmed", res))


@app.command("cancel")
def cancel(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
    reason: str | None = typer.Option(None, "--reason", help="Why the booking is cancelled."),
) -> None:
    """Cancel a booked/confirmed node + refund its covering payment (advisor)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.cancel_booking(itinerary_id, node_id, reason=reason))
    render.emit(state.json_mode, res, lambda: render.kv_panel("cancelled", res))


@app.command("reconcile")
def reconcile(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
) -> None:
    """Reconcile Σ(paid invoice lines) ⇔ Σ(booked node costs)."""
    state = state_of(ctx)
    res = run_op(ctx, lambda ovb: ovb.get_reconciliation(itinerary_id))
    render.emit(state.json_mode, res, lambda: render.kv_panel("reconciliation", res))
