"""Itinerary fork — a versioned clone of the graph (M004/G2, decision D-FORK).

A fork is a fresh :class:`Itinerary` whose ``forked_from_id`` points at a baseline
and which carries a deep copy of the baseline's nodes and edges. The copy honours
the node lifecycle (mvp.md §4):

* **Pre-booked nodes copy in editable.** ``idea`` / ``proposed`` keep their status;
  ``approved`` is **demoted to ``proposed``** so the traveler can rework it in the
  fork without first demoting (the baseline's approved node is untouched).
* **``booked`` / ``confirmed`` nodes copy in carried-LOCKED.** Their status is
  preserved, so the G1 status gate (`services/itineraries._check_status_gate`)
  makes them immutable in the fork exactly as in the baseline — you cannot fork
  away a paid booking.

Every copied node records its origin via ``forked_from_node_id`` so the G3 diff /
reconcile surface can pair fork↔baseline nodes by lineage. PostGIS ``location`` /
``route`` (omitted from the ORM) are copied with a single lineage-joined UPDATE so
a forked itinerary stays analyzable (G3 runs Analyze on the fork before reconcile).

Authorization lives in the router (owner / creator / advisor); this service trusts
its caller and only validates that the baseline exists.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Edge,
    ForkStatus,
    Itinerary,
    ItineraryStatus,
    Node,
    NodeStatus,
)
from app.services.itineraries import (
    ActorContext,
    ItineraryError,
    ItineraryOutcome,
    _write_edge_history,
    _write_node_history,
)

logger = logging.getLogger("ov_black.fork")

# Nodes in these statuses copy into the fork with their status PRESERVED — the G1
# gate then keeps them immutable (carried locked). Everything else copies editable.
_CARRY_LOCKED: frozenset[NodeStatus] = frozenset({NodeStatus.booked, NodeStatus.confirmed})


def _forked_status(status: NodeStatus) -> NodeStatus:
    """The status a baseline node takes in the fork.

    booked/confirmed → preserved (carried locked); approved → demoted to proposed
    (pre-booked, so editable in the fork); idea/proposed/discarded → unchanged.
    """
    if status in _CARRY_LOCKED:
        return status
    if status is NodeStatus.approved:
        return NodeStatus.proposed
    return status


async def fork_itinerary(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    title: str | None = None,
) -> Itinerary | ItineraryError:
    """Deep-copy ``itinerary_id`` into a new fork itinerary; returns the fork row.

    The whole copy lands in one transaction. Node/edge inserts each write an
    ``op='insert'`` history row (the fork relationship itself is recorded on the
    node via ``forked_from_node_id``; ``node_history.op`` is constrained to
    insert/update/delete).
    """
    baseline = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if baseline is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    fork = Itinerary(
        client_id=baseline.client_id,
        created_by=actor.user_id,
        title=title or f"{baseline.title} (fork)",
        status=ItineraryStatus.draft,
        forked_from_id=baseline.id,
        fork_status=ForkStatus.open,
    )
    session.add(fork)
    await session.flush()  # assign fork.id

    baseline_nodes = list(
        (await session.execute(select(Node).where(Node.itinerary_id == itinerary_id)))
        .scalars()
        .all()
    )

    new_nodes: list[Node] = []
    for old in baseline_nodes:
        clone = Node(
            itinerary_id=fork.id,
            parent_subgraph_id=None,  # remapped in pass 2
            type=old.type,
            status=_forked_status(old.status),
            title=old.title,
            source=old.source,
            source_id=old.source_id,
            metadata_=dict(old.metadata_ or {}),
            starts_at=old.starts_at,
            altitude_m=old.altitude_m,
            is_selected_alt=old.is_selected_alt,
            attached_to_node_id=None,  # remapped in pass 2
            role=old.role,
            template_id=old.template_id,
            template_node_id=old.template_node_id,
            template_version=old.template_version,
            cost_amount=old.cost_amount,
            cost_currency=old.cost_currency,
            cost_kind=old.cost_kind,
            forked_from_node_id=old.id,
        )
        session.add(clone)
        new_nodes.append(clone)
    await session.flush()  # assign clone ids

    id_map: dict[uuid.UUID, uuid.UUID] = {
        old.id: clone.id for old, clone in zip(baseline_nodes, new_nodes, strict=True)
    }

    # Pass 2: remap the self-referential FKs (subgraph parent, attached note) onto
    # the fork's own node ids. A reference outside the copied set resolves to None.
    for old, clone in zip(baseline_nodes, new_nodes, strict=True):
        if old.parent_subgraph_id is not None:
            clone.parent_subgraph_id = id_map.get(old.parent_subgraph_id)
        if old.attached_to_node_id is not None:
            clone.attached_to_node_id = id_map.get(old.attached_to_node_id)
    await session.flush()

    # PostGIS columns are invisible to the ORM (0014 note) — copy location/route
    # in one shot via the lineage we just stamped, so the fork stays geo-analyzable.
    await session.execute(
        text(
            """
            update public.nodes f
               set location = o.location,
                   route = o.route
              from public.nodes o
             where f.forked_from_node_id = o.id
               and f.itinerary_id = :fork_id
               and (o.location is not null or o.route is not null)
            """
        ),
        {"fork_id": fork.id},
    )

    baseline_edges = list(
        (await session.execute(select(Edge).where(Edge.itinerary_id == itinerary_id)))
        .scalars()
        .all()
    )
    new_edges: list[Edge] = []
    for edge in baseline_edges:
        new_from = id_map.get(edge.from_node_id)
        new_to = id_map.get(edge.to_node_id)
        if new_from is None or new_to is None:
            continue  # defensive: an edge touching a node outside the copied set
        clone_edge = Edge(
            itinerary_id=fork.id,
            from_node_id=new_from,
            to_node_id=new_to,
            type=edge.type,
            metadata_=dict(edge.metadata_ or {}),
        )
        session.add(clone_edge)
        new_edges.append(clone_edge)
    await session.flush()

    # Same-transaction history for every copied node + edge (op='insert').
    for clone in new_nodes:
        await _write_node_history(
            session,
            node_id=clone.id,
            itinerary_id=fork.id,
            op="insert",
            actor=actor,
            before=None,
            after=_snapshot_forked_node(clone),
        )
    for clone_edge in new_edges:
        await _write_edge_history(
            session,
            edge_id=clone_edge.id,
            itinerary_id=fork.id,
            op="insert",
            actor=actor,
            before=None,
            after={
                "id": str(clone_edge.id),
                "itinerary_id": str(clone_edge.itinerary_id),
                "from_node_id": str(clone_edge.from_node_id),
                "to_node_id": str(clone_edge.to_node_id),
                "type": clone_edge.type.value,
                "metadata": clone_edge.metadata_,
            },
        )

    await session.commit()
    await session.refresh(fork)
    logger.info(
        "itinerary.fork",
        extra={
            "fork_id": str(fork.id),
            "forked_from_id": str(baseline.id),
            "node_count": len(new_nodes),
            "edge_count": len(new_edges),
            "actor_kind": actor.kind.value,
        },
    )
    return fork


def _snapshot_forked_node(node: Node) -> dict[str, str | None]:
    """Minimal audit snapshot for a freshly-forked node, incl. its lineage."""
    return {
        "id": str(node.id),
        "itinerary_id": str(node.itinerary_id),
        "forked_from_node_id": (
            str(node.forked_from_node_id) if node.forked_from_node_id else None
        ),
        "status": node.status.value if isinstance(node.status, NodeStatus) else node.status,
        "title": node.title,
    }
