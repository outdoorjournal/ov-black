"""Assemble a kernel ``Graph`` from a served graph view (Phase 5).

The kernel's analysis layer (``app.kernel.analysis``) is pure — it judges a
``Graph`` value. This module is the one place a persisted itinerary becomes
that value, so the API's findings surface, and anything else that wants the
feasibility read, analyze exactly the same projection:

* nodes carry their decoded canonical schedule (stashed on ``NodeOut`` by the
  graph read), their provenance (``date_sensitive`` mirrors
  ``kernel_sync.is_date_sensitive``: provider-sourced flights), and their
  metadata as ``content`` — the kernel reads well-known keys (``location`` /
  ``from_location`` / ``to_location`` coords) and ignores the rest;
* subgraph children are excluded — they ride inside their parent's slot, and
  analyzing them against the parent would report the parent overlapping its
  own journey;
* edges keep their type; a ``follows`` edge picks up ``min_gap_minutes`` from
  its metadata when an int is present (no DB column exists yet — the kernel
  is the only home of the constraint).
"""

from __future__ import annotations

from typing import Any

from app.kernel import Edge as KernelEdge
from app.kernel import Graph as KernelGraph
from app.kernel import Node as KernelNode
from app.kernel import Provenance
from app.models.itinerary import NodeType


def _min_gap_minutes(metadata: Any) -> int | None:
    if not isinstance(metadata, dict):
        return None
    gap = metadata.get("min_gap_minutes")
    if isinstance(gap, int) and not isinstance(gap, bool) and gap > 0:
        return gap
    return None


def kernel_graph_from_view(view: Any) -> KernelGraph:
    """A ``GraphView`` (itinerary + NodeOut rows + EdgeOut rows) → kernel Graph."""
    nodes: dict[str, KernelNode] = {}
    for n in view.nodes:
        if n.parent_subgraph_id is not None:
            continue
        provenance = (
            Provenance(
                source=n.source,
                source_id=n.source_id,
                date_sensitive=n.type is NodeType.flight,
            )
            if n.source is not None
            else None
        )
        nodes[str(n.id)] = KernelNode(
            id=str(n.id),
            type=n.type,
            title=n.title,
            status=n.status,
            schedule=getattr(n, "kernel_schedule", None),
            provenance=provenance,
            needs_revalidation=bool(getattr(n, "needs_revalidation", False)),
            content=n.metadata if isinstance(n.metadata, dict) else {},
        )

    edges: dict[str, KernelEdge] = {}
    for e in view.edges:
        from_id, to_id = str(e.from_node_id), str(e.to_node_id)
        if from_id not in nodes or to_id not in nodes:
            continue  # an endpoint was a subgraph child we excluded
        edges[str(e.id)] = KernelEdge(
            id=str(e.id),
            from_id=from_id,
            to_id=to_id,
            type=e.type,
            min_gap_minutes=_min_gap_minutes(e.metadata),
        )

    return KernelGraph(
        anchor_date=view.itinerary.anchor_date,
        nodes=nodes,
        edges=edges,
    )
