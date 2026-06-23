"""`ovb node` and `ovb edge` — mutate the itinerary graph directly."""

import json
from typing import Any

import typer

from ovb.cli import render
from ovb.cli._run import run_op, state_of

node_app = typer.Typer(help="Nodes: add, propose from inventory, edit, delete.")
edge_app = typer.Typer(help="Edges: connect or disconnect nodes.")


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--metadata must be JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("--metadata must be a JSON object")
    return parsed


@node_app.command("add")
def node_add(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    type: str = typer.Option(..., "--type", help="Node type (hotel, flight, experience, …)."),
    title: str = typer.Option("", "--title", "-t"),
    status: str = typer.Option("idea", "--status"),
    cost_amount: str | None = typer.Option(None, "--cost-amount"),
    cost_currency: str | None = typer.Option(None, "--cost-currency"),
    cost_kind: str | None = typer.Option(None, "--cost-kind", help="per_person | total"),
    source: str | None = typer.Option(None, "--source"),
    source_id: str | None = typer.Option(None, "--source-id"),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON object."),
) -> None:
    """Insert a node into the graph."""
    state = state_of(ctx)
    meta = _parse_metadata(metadata)
    res = run_op(
        ctx,
        lambda ovb: ovb.add_node(
            itinerary_id,
            type=type,
            title=title,
            status=status,
            cost_amount=cost_amount,
            cost_currency=cost_currency,
            cost_kind=cost_kind,
            source=source,
            source_id=source_id,
            metadata=meta,
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("node", res))


@node_app.command("from-inventory")
def node_from_inventory(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    source: str = typer.Option(..., "--source", help="Provider source (duffel, ratehawk, ov…)."),
    source_id: str = typer.Option(..., "--source-id", help="Provider item id."),
    status: str = typer.Option("proposed", "--status"),
) -> None:
    """Propose a node from a live inventory item (typed card metadata)."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.node_from_inventory(
            itinerary_id, source=source, source_id=source_id, status=status
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("node", res))


@node_app.command("update")
def node_update(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(..., help="Itinerary UUID."),
    node_id: str = typer.Argument(..., help="Node UUID."),
    status: str | None = typer.Option(None, "--status"),
    title: str | None = typer.Option(None, "--title"),
    type: str | None = typer.Option(None, "--type"),
    cost_amount: str | None = typer.Option(None, "--cost-amount"),
    cost_currency: str | None = typer.Option(None, "--cost-currency"),
    cost_kind: str | None = typer.Option(None, "--cost-kind"),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON object (replaces)."),
) -> None:
    """Patch a node (only the flags you pass are sent)."""
    state = state_of(ctx)
    fields: dict[str, Any] = {
        "status": status,
        "title": title,
        "type": type,
        "cost_amount": cost_amount,
        "cost_currency": cost_currency,
        "cost_kind": cost_kind,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    if metadata is not None:
        fields["metadata"] = _parse_metadata(metadata)
    if not fields:
        raise typer.BadParameter("pass at least one field to update")
    res = run_op(ctx, lambda ovb: ovb.update_node(itinerary_id, node_id, fields=fields))
    render.emit(state.json_mode, res, lambda: render.kv_panel("node", res))


@node_app.command("delete")
def node_delete(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    node_id: str = typer.Argument(...),
) -> None:
    """Delete a node."""
    state = state_of(ctx)
    run_op(ctx, lambda ovb: ovb.delete_node(itinerary_id, node_id))
    render.emit(state.json_mode, {"ok": True, "deleted": node_id}, lambda: f"deleted {node_id}")


@edge_app.command("add")
def edge_add(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    from_node_id: str = typer.Option(..., "--from", help="Source node UUID."),
    to_node_id: str = typer.Option(..., "--to", help="Target node UUID."),
    type: str = typer.Option("follows", "--type", help="follows, alternative_to, …"),
) -> None:
    """Connect two nodes with an edge."""
    state = state_of(ctx)
    res = run_op(
        ctx,
        lambda ovb: ovb.add_edge(
            itinerary_id, from_node_id=from_node_id, to_node_id=to_node_id, type=type
        ),
    )
    render.emit(state.json_mode, res, lambda: render.kv_panel("edge", res))


@edge_app.command("delete")
def edge_delete(
    ctx: typer.Context,
    itinerary_id: str = typer.Argument(...),
    edge_id: str = typer.Argument(...),
) -> None:
    """Delete an edge."""
    state = state_of(ctx)
    run_op(ctx, lambda ovb: ovb.delete_edge(itinerary_id, edge_id))
    render.emit(state.json_mode, {"ok": True, "deleted": edge_id}, lambda: f"deleted {edge_id}")
