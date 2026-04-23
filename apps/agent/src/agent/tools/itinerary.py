"""Itinerary read tools — list trips, fetch one, find alternatives."""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, get_json
from agent.backend import pin_ctx


@tool
async def list_itineraries() -> dict:
    """List every itinerary owned by the calling client.

    Returns ``{itineraries: [{id, title, status, created_at,
    updated_at, approved_at}...]}`` ordered newest-updated first.
    Includes draft and approved rows. Empty list is a valid response
    for a client in onboarding.
    """
    return await get_json("/me/itineraries")


@tool
async def get_itinerary(itinerary_id: str | None = None) -> dict:
    """Fetch the full graph for one itinerary.

    Args:
        itinerary_id: UUID of the itinerary to read. If omitted and the
            session is pinned, uses the pinned id. Required for Q&A
            calls that span trips.

    Returns the itinerary envelope with nodes + edges + history as
    assembled by the graph service. Only readable by the owning client,
    the assigned advisor, or an agent acting on their behalf.
    """
    target = itinerary_id or (pin_ctx.get() or {}).get("itinerary_id")
    if not target:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return await get_json(f"/itinerary/{target}")


@tool
async def list_alternatives(node_id: str) -> dict:
    """List cluster of ``alternative_to`` siblings for a node.

    Use during planning when the client is deciding between options for
    the same slot (three hotel candidates, two restaurants for
    anniversary dinner). Returns the neighbour nodes with their status.

    Implementation note: fetches the full itinerary and filters client-
    side. This is fine for M001 — itineraries are small. Revisit with a
    dedicated endpoint when size grows.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    graph = await get_json(f"/itinerary/{itinerary_id}")

    alternatives: list[dict[str, Any]] = []
    edges = graph.get("edges") or []
    nodes_by_id = {n["id"]: n for n in (graph.get("nodes") or [])}
    for edge in edges:
        if edge.get("type") != "alternative_to":
            continue
        if edge.get("from_node_id") == node_id:
            target = nodes_by_id.get(edge.get("to_node_id"))
            if target:
                alternatives.append(target)
        elif edge.get("to_node_id") == node_id:
            target = nodes_by_id.get(edge.get("from_node_id"))
            if target:
                alternatives.append(target)
    return {"node_id": node_id, "alternatives": alternatives}
