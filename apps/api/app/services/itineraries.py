"""Itinerary graph CRUD with same-transaction history writes.

Every mutation (node or edge insert/update/delete) writes a matching row to
``node_history`` / ``edge_history`` in the SAME session before commit. We
deliberately do NOT use Postgres triggers for this — see S02 research doc
"Decision: history via service-layer writes, NOT triggers": actor attribution
needs the request-scoped ``ActorContext`` which triggers cannot see, and
coupling the audit write to the application code keeps the invariant visible
to reviewers.

Outcomes are enumerated so the HTTP layer can map each to a specific status
without leaking DB internals. The provenance gate (source ⇔ source_id) is
enforced here as a guardrail; the DB ``nodes_provenance_complete`` CHECK
constraint is the belt-and-suspenders.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from typing import Any, NamedTuple

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Edge,
    EdgeHistory,
    EdgeType,
    Itinerary,
    ItineraryStatus,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
)

logger = logging.getLogger("ov_black.itineraries")


class ItineraryOutcome(str, enum.Enum):
    """All terminal states of an itinerary mutation."""

    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID_PARENT = "invalid_parent"
    INVALID_PROVENANCE = "invalid_provenance"
    VALIDATION_ERROR = "validation_error"
    FORBIDDEN = "forbidden"
    LOCKED = "locked"


class ActorKind(str, enum.Enum):
    """Who initiated the mutation. Persisted on every history row."""

    USER = "user"
    AGENT = "agent"
    ADVISOR = "advisor"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Request-scoped principal used to attribute history rows.

    ``user_id`` is the Supabase ``auth.users.id`` (UUID) when a human user
    initiated the change. ``actor_id`` is an opaque string for non-user
    actors (agent session id, advisor id, system job name).
    """

    user_id: uuid.UUID | None
    kind: ActorKind
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class ItineraryError:
    """Failure envelope returned by service functions when outcome != OK."""

    outcome: ItineraryOutcome
    detail: str | None = None


class NodeOut(NamedTuple):
    """Flattened node row + CTE ``depth`` for graph assembly responses."""

    id: uuid.UUID
    itinerary_id: uuid.UUID
    parent_subgraph_id: uuid.UUID | None
    type: NodeType
    status: NodeStatus
    title: str
    source: str | None
    source_id: str | None
    metadata: dict[str, Any]
    depth: int


class EdgeOut(NamedTuple):
    """Edge row as it appears in a graph assembly response."""

    id: uuid.UUID
    itinerary_id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any]


class GraphView(NamedTuple):
    """Assembled output of :func:`get_itinerary_graph`."""

    itinerary: Itinerary
    nodes: list[NodeOut]
    edges: list[EdgeOut]


# ── Snapshot helpers ────────────────────────────────────────────────────────


def _snapshot_node(node: Node) -> dict[str, Any]:
    """JSON-safe snapshot of a node for before/after history columns."""
    return {
        "id": str(node.id),
        "itinerary_id": str(node.itinerary_id),
        "parent_subgraph_id": (
            str(node.parent_subgraph_id) if node.parent_subgraph_id else None
        ),
        "type": node.type.value if isinstance(node.type, NodeType) else node.type,
        "status": (
            node.status.value if isinstance(node.status, NodeStatus) else node.status
        ),
        "title": node.title,
        "source": node.source,
        "source_id": node.source_id,
        "metadata": node.metadata_,
    }


def _snapshot_edge(edge: Edge) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "itinerary_id": str(edge.itinerary_id),
        "from_node_id": str(edge.from_node_id),
        "to_node_id": str(edge.to_node_id),
        "type": edge.type.value if isinstance(edge.type, EdgeType) else edge.type,
        "metadata": edge.metadata_,
    }


async def _write_node_history(
    session: AsyncSession,
    *,
    node_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    op: str,
    actor: ActorContext,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append a row to node_history in the same session as the mutation."""
    session.add(
        NodeHistory(
            node_id=node_id,
            itinerary_id=itinerary_id,
            op=op,
            actor_user_id=actor.user_id,
            actor_kind=actor.kind.value,
            actor_id=actor.actor_id,
            before=before,
            after=after,
        )
    )
    logger.info(
        "itinerary.history.write",
        extra={"table": "node_history", "op": op, "node_id": str(node_id)},
    )


async def _write_edge_history(
    session: AsyncSession,
    *,
    edge_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    op: str,
    actor: ActorContext,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        EdgeHistory(
            edge_id=edge_id,
            itinerary_id=itinerary_id,
            op=op,
            actor_user_id=actor.user_id,
            actor_kind=actor.kind.value,
            actor_id=actor.actor_id,
            before=before,
            after=after,
        )
    )
    logger.info(
        "itinerary.history.write",
        extra={"table": "edge_history", "op": op, "edge_id": str(edge_id)},
    )


# ── Provenance gate ─────────────────────────────────────────────────────────


def _check_provenance(
    source: str | None, source_id: str | None
) -> ItineraryError | None:
    if (source is None) != (source_id is None):
        return ItineraryError(
            outcome=ItineraryOutcome.INVALID_PROVENANCE,
            detail="source and source_id must be provided together",
        )
    return None


# ── Lock gate ───────────────────────────────────────────────────────────────


async def _check_lock(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    actor: ActorContext,
) -> ItineraryError | None:
    """Reject non-advisor writes to an itinerary locked by a different user.

    Advisors always bypass — they hold the lock during their editing session
    and the advisor guard at the router layer is the authoritative gate.
    A null ``locked_by`` means the itinerary is unlocked and any actor may
    write. A ``locked_by`` that matches ``actor.user_id`` means the caller
    owns the lock (same advisor re-entering).
    """
    if actor.kind is ActorKind.ADVISOR:
        return None
    row = (
        await session.execute(
            select(Itinerary.locked_by).where(Itinerary.id == itinerary_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if actor.user_id is not None and row == actor.user_id:
        return None
    return ItineraryError(
        outcome=ItineraryOutcome.LOCKED,
        detail="locked_by_advisor",
    )


# ── Public service surface ──────────────────────────────────────────────────


async def create_itinerary(
    session: AsyncSession,
    actor: ActorContext,
    *,
    title: str,
    client_id: uuid.UUID | None = None,
) -> Itinerary:
    """Create a new itinerary container.

    Itineraries themselves are not audited in node_history / edge_history —
    those tables only track graph mutations. Auditing of itinerary-level
    changes can land in a follow-up slice if needed.
    """
    itinerary = Itinerary(
        title=title,
        client_id=client_id,
        created_by=actor.user_id,
        status=ItineraryStatus.draft,
    )
    session.add(itinerary)
    await session.flush()
    await session.commit()
    logger.info(
        "itinerary.create",
        extra={
            "itinerary_id": str(itinerary.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return itinerary


async def get_itinerary_graph(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
) -> GraphView | ItineraryError:
    """Assemble (itinerary, nodes-with-depth, edges) with one recursive CTE.

    Depth 0 = root nodes (parent_subgraph_id IS NULL). Each deeper level
    follows the self-FK. The CTE is a single round-trip; edges come back in
    a second SELECT. No N+1.
    """
    itinerary = (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
    if itinerary is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    cte_sql = text(
        """
        with recursive subgraph(
            id, itinerary_id, parent_subgraph_id, type, status, title,
            source, source_id, metadata, depth
        ) as (
            select n.id, n.itinerary_id, n.parent_subgraph_id, n.type, n.status,
                   n.title, n.source, n.source_id, n.metadata, 0
              from public.nodes n
             where n.itinerary_id = :iid
               and n.parent_subgraph_id is null
            union all
            select c.id, c.itinerary_id, c.parent_subgraph_id, c.type, c.status,
                   c.title, c.source, c.source_id, c.metadata, s.depth + 1
              from public.nodes c
              join subgraph s on c.parent_subgraph_id = s.id
             where c.itinerary_id = :iid
        )
        select id, itinerary_id, parent_subgraph_id, type, status, title,
               source, source_id, metadata, depth
          from subgraph
         order by depth, id
        """
    )
    node_rows = (await session.execute(cte_sql, {"iid": itinerary_id})).all()
    nodes: list[NodeOut] = [
        NodeOut(
            id=row.id,
            itinerary_id=row.itinerary_id,
            parent_subgraph_id=row.parent_subgraph_id,
            type=NodeType(row.type),
            status=NodeStatus(row.status),
            title=row.title,
            source=row.source,
            source_id=row.source_id,
            metadata=row.metadata,
            depth=row.depth,
        )
        for row in node_rows
    ]

    edge_rows = (
        await session.execute(
            select(Edge)
            .where(Edge.itinerary_id == itinerary_id)
            .order_by(Edge.created_at)
        )
    ).scalars().all()
    edges: list[EdgeOut] = [
        EdgeOut(
            id=edge.id,
            itinerary_id=edge.itinerary_id,
            from_node_id=edge.from_node_id,
            to_node_id=edge.to_node_id,
            type=edge.type,
            metadata=edge.metadata_,
        )
        for edge in edge_rows
    ]

    return GraphView(itinerary=itinerary, nodes=nodes, edges=edges)


async def add_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    type: NodeType,
    status: NodeStatus = NodeStatus.idea,
    title: str = "",
    parent_subgraph_id: uuid.UUID | None = None,
    source: str | None = None,
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Node | ItineraryError:
    """Insert a node + its history row in the same transaction."""
    prov_err = _check_provenance(source, source_id)
    if prov_err is not None:
        return prov_err

    # Confirm parent itinerary exists up front so we return NOT_FOUND
    # instead of an FK violation.
    itinerary_exists = (
        await session.execute(
            select(Itinerary.id).where(Itinerary.id == itinerary_id)
        )
    ).scalar_one_or_none()
    if itinerary_exists is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_lock(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    if parent_subgraph_id is not None:
        parent = (
            await session.execute(
                select(Node).where(Node.id == parent_subgraph_id)
            )
        ).scalar_one_or_none()
        if parent is None or parent.itinerary_id != itinerary_id:
            return ItineraryError(
                outcome=ItineraryOutcome.INVALID_PARENT,
                detail="parent_subgraph_id does not belong to this itinerary",
            )

    node = Node(
        itinerary_id=itinerary_id,
        parent_subgraph_id=parent_subgraph_id,
        type=type,
        status=status,
        title=title,
        source=source,
        source_id=source_id,
        metadata_=metadata or {},
    )
    session.add(node)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "insert_node", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="insert",
        actor=actor,
        before=None,
        after=_snapshot_node(node),
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "insert_node",
            "node_id": str(node.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return node


async def update_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    **fields: Any,
) -> Node | ItineraryError:
    """Update a node + capture before/after snapshots in history.

    Only a small whitelist of fields can be changed through this path — the
    primary key, itinerary_id, and timestamps are never mutable.
    """
    node = (
        await session.execute(
            select(Node).where(
                Node.id == node_id,
                Node.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if node is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_lock(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    allowed = {"type", "status", "title", "source", "source_id", "metadata"}
    updates: dict[str, Any] = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return node  # No-op update is idempotent — don't write history.

    new_source = updates.get("source", node.source)
    new_source_id = updates.get("source_id", node.source_id)
    prov_err = _check_provenance(new_source, new_source_id)
    if prov_err is not None:
        return prov_err

    before = _snapshot_node(node)
    for key, value in updates.items():
        if key == "metadata":
            node.metadata_ = value
        else:
            setattr(node, key, value)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "update_node", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_node_history(
        session,
        node_id=node.id,
        itinerary_id=itinerary_id,
        op="update",
        actor=actor,
        before=before,
        after=_snapshot_node(node),
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "update_node",
            "node_id": str(node.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return node


async def delete_node(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
) -> ItineraryError | None:
    """Delete a node + write a history row with the pre-delete snapshot."""
    node = (
        await session.execute(
            select(Node).where(
                Node.id == node_id,
                Node.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if node is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_lock(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    before = _snapshot_node(node)
    await session.delete(node)
    await session.flush()
    await _write_node_history(
        session,
        node_id=node_id,
        itinerary_id=itinerary_id,
        op="delete",
        actor=actor,
        before=before,
        after=None,
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "delete_node",
            "node_id": str(node_id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return None


async def add_edge(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    from_node_id: uuid.UUID,
    to_node_id: uuid.UUID,
    type: EdgeType,
    metadata: dict[str, Any] | None = None,
) -> Edge | ItineraryError:
    """Insert an edge + its history row. The DB enforces no self-loops."""
    itinerary_exists = (
        await session.execute(
            select(Itinerary.id).where(Itinerary.id == itinerary_id)
        )
    ).scalar_one_or_none()
    if itinerary_exists is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_lock(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    edge = Edge(
        itinerary_id=itinerary_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        type=type,
        metadata_=metadata or {},
    )
    session.add(edge)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        logger.info(
            "itinerary.mutate.integrity_error",
            extra={"op": "insert_edge", "reason": str(exc.orig)},
        )
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail=_integrity_detail(exc),
        )

    await _write_edge_history(
        session,
        edge_id=edge.id,
        itinerary_id=itinerary_id,
        op="insert",
        actor=actor,
        before=None,
        after=_snapshot_edge(edge),
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "insert_edge",
            "edge_id": str(edge.id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return edge


async def delete_edge(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    edge_id: uuid.UUID,
) -> ItineraryError | None:
    edge = (
        await session.execute(
            select(Edge).where(
                Edge.id == edge_id,
                Edge.itinerary_id == itinerary_id,
            )
        )
    ).scalar_one_or_none()
    if edge is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)

    lock_err = await _check_lock(session, itinerary_id, actor)
    if lock_err is not None:
        return lock_err

    before = _snapshot_edge(edge)
    # Use a Core delete so we don't need to load relationships.
    await session.execute(delete(Edge).where(Edge.id == edge_id))
    await session.flush()
    await _write_edge_history(
        session,
        edge_id=edge_id,
        itinerary_id=itinerary_id,
        op="delete",
        actor=actor,
        before=before,
        after=None,
    )
    await session.commit()
    logger.info(
        "itinerary.mutate",
        extra={
            "op": "delete_edge",
            "edge_id": str(edge_id),
            "actor_kind": actor.kind.value,
            "actor_id": actor.actor_id,
        },
    )
    return None


async def acquire_lock(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Take the editor-session lock for ``itinerary_id``.

    Succeeds if the itinerary is either unlocked or already locked by the
    same user (same-user re-acquire is idempotent). Advisor-only — the
    router layer enforces that guard before calling here.
    """
    stmt = (
        update(Itinerary)
        .where(
            Itinerary.id == itinerary_id,
            or_(
                Itinerary.locked_by.is_(None),
                Itinerary.locked_by == actor.user_id,
            ),
        )
        .values(locked_by=actor.user_id, locked_at=func.now())
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        await session.rollback()
        logger.info(
            "itinerary.lock.rejected",
            extra={
                "itinerary_id": str(itinerary_id),
                "sub_hint": (actor.actor_id or "")[:8],
            },
        )
        return ItineraryError(
            outcome=ItineraryOutcome.LOCKED,
            detail="already_locked",
        )
    await session.commit()
    await session.refresh(row)
    logger.info(
        "itinerary.lock.acquired",
        extra={
            "itinerary_id": str(itinerary_id),
            "user_id": str(actor.user_id) if actor.user_id else None,
        },
    )
    return row


async def release_lock(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Release the editor-session lock held by ``actor``.

    Idempotent: if the caller doesn't hold the lock (including the already-
    unlocked case), returns the current row unchanged — not an error.
    """
    stmt = (
        update(Itinerary)
        .where(
            Itinerary.id == itinerary_id,
            Itinerary.locked_by == actor.user_id,
        )
        .values(locked_by=None, locked_at=None)
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        current = (
            await session.execute(
                select(Itinerary).where(Itinerary.id == itinerary_id)
            )
        ).scalar_one_or_none()
        if current is None:
            return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
        return current
    await session.commit()
    await session.refresh(row)
    logger.info(
        "itinerary.lock.released",
        extra={
            "itinerary_id": str(itinerary_id),
            "queue_depth_drained": 0,
        },
    )
    return row


async def approve_itinerary(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Flip an itinerary from ``draft`` to ``approved``.

    Returns ``VALIDATION_ERROR`` (detail ``already_approved``) if the row is
    not currently in ``draft`` state.
    """
    stmt = (
        update(Itinerary)
        .where(
            Itinerary.id == itinerary_id,
            Itinerary.status == ItineraryStatus.draft,
        )
        .values(
            status=ItineraryStatus.approved,
            approved_by=actor.user_id,
            approved_at=func.now(),
        )
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        await session.rollback()
        return ItineraryError(
            outcome=ItineraryOutcome.VALIDATION_ERROR,
            detail="already_approved",
        )
    await session.commit()
    await session.refresh(row)
    node_count = (
        await session.execute(
            select(func.count(Node.id)).where(Node.itinerary_id == itinerary_id)
        )
    ).scalar_one()
    logger.info(
        "itinerary.approved",
        extra={
            "itinerary_id": str(itinerary_id),
            "user_id": str(actor.user_id) if actor.user_id else None,
            "node_count": int(node_count),
        },
    )
    return row


def _integrity_detail(exc: IntegrityError) -> str:
    """Extract a stable, caller-useful reason string from a DB error.

    We surface the constraint name when we can see it (nodes_provenance_complete,
    edges_no_self_loop, …) because the slice plan's failure-visibility note
    says the constraint name must be visible in the error.
    """
    msg = str(getattr(exc, "orig", exc))
    for name in (
        "nodes_provenance_complete",
        "edges_no_self_loop",
    ):
        if name in msg:
            return name
    return "integrity_error"
