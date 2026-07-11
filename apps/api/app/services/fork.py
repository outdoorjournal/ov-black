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
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AnalysisStatus,
    Edge,
    EdgeType,
    FindingSeverity,
    ForkStatus,
    Itinerary,
    Node,
    NodeStatus,
)
from app.services.analyze import get_analysis, list_analyses
from app.services.itineraries import (
    ActorContext,
    GraphView,
    ItineraryError,
    ItineraryOutcome,
    NodeOut,
    _write_edge_history,
    _write_node_history,
    add_edge,
    add_node,
    delete_edge,
    delete_node,
    get_itinerary_graph,
    update_node,
)

logger = logging.getLogger("ov_black.fork")

# Nodes in these statuses copy into the fork with their status PRESERVED — the G1
# gate then keeps them immutable (carried locked). Everything else copies editable.
_CARRY_LOCKED: frozenset[NodeStatus] = frozenset({NodeStatus.booked, NodeStatus.confirmed})


def _forked_status(status: NodeStatus) -> NodeStatus:
    """The status a baseline node takes in the fork.

    booked/confirmed → preserved (carried locked); approved → demoted to pending
    (pre-booked, so editable in the fork — the trunk node stays approved/locked;
    a fork is where amendments to it get *proposed*); pending/discarded →
    unchanged.
    """
    if status in _CARRY_LOCKED:
        return status
    if status is NodeStatus.approved:
        return NodeStatus.pending
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
        forked_from_id=baseline.id,
        fork_status=ForkStatus.open,
    )
    session.add(fork)
    await session.flush()  # assign fork.id

    # Soft-deleted nodes are gone from view — a fork must not resurrect them.
    baseline_nodes = list(
        (
            await session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary_id,
                    Node.deleted_at.is_(None),
                )
            )
        )
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


# ──────────────────────────────────────────────────────────────────────────────
# G3 — diff + reconcile
# ──────────────────────────────────────────────────────────────────────────────
#
# A fork diverges from its baseline. ``diff_fork`` pairs the two graphs by the
# ``forked_from_node_id`` lineage G2 stamped and buckets the divergence into
# added / removed / changed / moved. ``reconcile_fork`` (advisor-only — gated in
# the router) folds *accepted* changes back into the LIVE baseline through the
# same ``update_node`` / ``delete_node`` / ``add_node`` service path, so the G1
# status gate keeps booked/confirmed nodes immutable (a booked baseline node's
# change is refused per-change, not applied). The traveler half is ``request_
# reconcile`` (stamp the ask) + ``abandon_fork``.


# The subset of changed fields reconcile can copy fork→baseline through
# ``update_node`` (its allowed-field whitelist). ``starts_at`` rides a separate
# raw copy; ``position`` is the moved path; both are excluded here.
_RECONCILABLE_CONTENT: frozenset[str] = frozenset(
    {
        "title",
        "type",
        "status",
        "source",
        "source_id",
        "metadata",
        "cost_amount",
        "cost_currency",
        "cost_kind",
    }
)


@dataclass(frozen=True, slots=True)
class NodeChange:
    """One divergence between a fork node and its baseline origin.

    ``change_id`` is a stable handle the reconcile API references in its
    decisions — the fork node id for added/changed/moved, the baseline node id
    for removed (these never collide). ``fields`` names the changed content
    fields (plus ``"position"`` when a content change also moved); empty for
    added/removed. ``before`` is the baseline snapshot, ``after`` the fork
    snapshot (one is None for added/removed).
    """

    change_id: uuid.UUID
    kind: str  # "added" | "removed" | "changed" | "moved"
    fork_node_id: uuid.UUID | None
    baseline_node_id: uuid.UUID | None
    fields: tuple[str, ...]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ForkDiff:
    """The full divergence of a fork from its baseline, bucketed by kind."""

    fork_id: uuid.UUID
    baseline_id: uuid.UUID
    added: list[NodeChange]
    removed: list[NodeChange]
    changed: list[NodeChange]
    moved: list[NodeChange]


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    """An advisor's accept/discard verdict on a single diff change."""

    change_id: uuid.UUID
    accept: bool


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """What actually happened to one decided change against the baseline.

    ``result`` is one of: ``applied`` (folded into the baseline), ``discarded``
    (advisor declined; baseline untouched), ``refused_booked`` (the baseline
    node is booked/confirmed — G1 keeps it immutable, surfaced not applied),
    ``failed`` (an unexpected service error), ``skipped`` (the change_id is no
    longer in the fresh diff — stale selection).
    """

    change_id: uuid.UUID
    kind: str
    result: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of a reconcile pass: the live baseline + fork + per-change log."""

    itinerary: Itinerary  # the live (baseline) itinerary, post-mutation
    fork: Itinerary  # the fork, with its updated fork_status / cleared request
    outcomes: list[ReconcileOutcome]


def _node_snapshot(n: NodeOut) -> dict[str, Any]:
    """JSON-safe before/after snapshot of a graph node for the diff response."""
    return {
        "id": str(n.id),
        "type": n.type.value,
        "status": n.status.value,
        "title": n.title,
        "source": n.source,
        "source_id": n.source_id,
        "metadata": n.metadata,
        "cost_amount": str(n.cost_amount) if n.cost_amount is not None else None,
        "cost_currency": n.cost_currency,
        "cost_kind": n.cost_kind.value if n.cost_kind is not None else None,
        "starts_at": n.starts_at,
        "duration_minutes": n.duration_minutes,
        "forked_from_node_id": (
            str(n.forked_from_node_id) if n.forked_from_node_id is not None else None
        ),
    }


def _changed_fields(baseline: NodeOut, fork: NodeOut) -> list[str]:
    """Names of the content fields that differ fork-vs-baseline.

    Applies the **intrinsic-demotion rule**: a status diff that is exactly
    ``approved → pending`` is G2's fork transform (not a user edit), so it is
    never reported. Every other field — and every other status transition — is.
    (With idea/proposed collapsed into pending this also swallows the case
    where a pre-collapse fork node sat at ``idea`` opposite an approved
    baseline — acceptable, and arguably the more correct read.)
    """
    fields: list[str] = []
    if baseline.title != fork.title:
        fields.append("title")
    if baseline.type is not fork.type:
        fields.append("type")
    if baseline.cost_amount != fork.cost_amount:
        fields.append("cost_amount")
    if baseline.cost_currency != fork.cost_currency:
        fields.append("cost_currency")
    if baseline.cost_kind is not fork.cost_kind:
        fields.append("cost_kind")
    if (baseline.starts_at, baseline.duration_minutes) != (fork.starts_at, fork.duration_minutes):
        fields.append("starts_at")
    if baseline.metadata != fork.metadata:
        fields.append("metadata")
    if baseline.source != fork.source:
        fields.append("source")
    if baseline.source_id != fork.source_id:
        fields.append("source_id")
    if baseline.status is not fork.status:
        is_fork_demotion = (
            baseline.status is NodeStatus.approved and fork.status is NodeStatus.pending
        )
        if not is_fork_demotion:
            fields.append("status")
    return fields


def _follows_neighbors(
    view: GraphView,
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, uuid.UUID]]:
    """(predecessor, successor) maps over the ``follows`` edges, keyed by node id."""
    pred: dict[uuid.UUID, uuid.UUID] = {}
    succ: dict[uuid.UUID, uuid.UUID] = {}
    for edge in view.edges:
        if edge.type is EdgeType.follows:
            succ[edge.from_node_id] = edge.to_node_id
            pred[edge.to_node_id] = edge.from_node_id
    return pred, succ


async def diff_fork(
    session: AsyncSession,
    *,
    fork_id: uuid.UUID,
) -> ForkDiff | ItineraryError:
    """Pair a fork against its baseline by lineage and bucket the divergence.

    Always computed fresh from the two live graphs (never cached) so a re-diff
    after a partial reconcile reflects the now-smaller delta. Returns
    ``NOT_FOUND`` for a missing itinerary and ``VALIDATION_ERROR`` (detail
    ``not_a_fork``) when the itinerary has no ``forked_from_id``.
    """
    fork_itin = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one_or_none()
    if fork_itin is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if fork_itin.forked_from_id is None:
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="not_a_fork")
    baseline_id = fork_itin.forked_from_id

    fork_view = await get_itinerary_graph(session, fork_id)
    if isinstance(fork_view, ItineraryError):
        return fork_view
    baseline_view = await get_itinerary_graph(session, baseline_id)
    if isinstance(baseline_view, ItineraryError):
        return baseline_view  # baseline purged mid-flight

    baseline_by_id = {n.id: n for n in baseline_view.nodes}
    fork_by_origin = {
        n.forked_from_node_id: n for n in fork_view.nodes if n.forked_from_node_id is not None
    }
    fork_to_origin = {n.id: n.forked_from_node_id for n in fork_view.nodes}
    b_pred, b_succ = _follows_neighbors(baseline_view)
    f_pred, f_succ = _follows_neighbors(fork_view)

    def origin_of(fork_node_id: uuid.UUID | None) -> uuid.UUID | None:
        """Map a fork node id back to the baseline node it was copied from."""
        if fork_node_id is None:
            return None
        return fork_to_origin.get(fork_node_id)

    added: list[NodeChange] = []
    removed: list[NodeChange] = []
    changed: list[NodeChange] = []
    moved: list[NodeChange] = []

    # removed: a baseline node no fork node points back to (deleted in the fork).
    for b in baseline_view.nodes:
        if b.id not in fork_by_origin:
            removed.append(
                NodeChange(
                    change_id=b.id,
                    kind="removed",
                    fork_node_id=None,
                    baseline_node_id=b.id,
                    fields=(),
                    before=_node_snapshot(b),
                    after=None,
                )
            )

    for f in fork_view.nodes:
        origin = f.forked_from_node_id
        # added: created in the fork, or its origin was deleted upstream.
        if origin is None or origin not in baseline_by_id:
            added.append(
                NodeChange(
                    change_id=f.id,
                    kind="added",
                    fork_node_id=f.id,
                    baseline_node_id=None,
                    fields=(),
                    before=None,
                    after=_node_snapshot(f),
                )
            )
            continue
        b = baseline_by_id[origin]
        content = _changed_fields(b, f)
        position_changed = (
            origin_of(f_pred.get(f.id)) != b_pred.get(b.id)
            or origin_of(f_succ.get(f.id)) != b_succ.get(b.id)
            or origin_of(f.parent_subgraph_id) != b.parent_subgraph_id
        )
        if content:
            # changed (content) — fold a co-occurring move into a "position" flag
            # so the UI shows one row per node (changed and moved stay disjoint).
            fields = (*content, "position") if position_changed else tuple(content)
            changed.append(
                NodeChange(
                    change_id=f.id,
                    kind="changed",
                    fork_node_id=f.id,
                    baseline_node_id=b.id,
                    fields=fields,
                    before=_node_snapshot(b),
                    after=_node_snapshot(f),
                )
            )
        elif position_changed:
            moved.append(
                NodeChange(
                    change_id=f.id,
                    kind="moved",
                    fork_node_id=f.id,
                    baseline_node_id=b.id,
                    fields=("position",),
                    before=_node_snapshot(b),
                    after=_node_snapshot(f),
                )
            )

    return ForkDiff(
        fork_id=fork_id,
        baseline_id=baseline_id,
        added=added,
        removed=removed,
        changed=changed,
        moved=moved,
    )


async def _feasibility_block(
    session: AsyncSession,
    *,
    fork_id: uuid.UUID,
    analysis_id: uuid.UUID | None,
    override_block: bool,
) -> ItineraryError | None:
    """Refuse reconcile when the fork's Analyze carries a ``block`` finding.

    Resolves the passed ``analysis_id`` or the fork's latest *completed* run.
    No completed run ⇒ no gate (the UI nudges the advisor to run Analyze, but a
    fork that was never analyzed isn't dead-ended). ``override_block`` is the
    advisor's explicit, logged escape hatch.
    """
    if override_block:
        logger.info("fork.reconcile.override_block", extra={"fork_id": str(fork_id)})
        return None
    findings = []
    if analysis_id is not None:
        got = await get_analysis(session, itinerary_id=fork_id, analysis_id=analysis_id)
        findings = list(got[1]) if got is not None else []
    else:
        runs = await list_analyses(session, itinerary_id=fork_id)
        completed = next((a for a in runs if a.status is AnalysisStatus.completed), None)
        if completed is None:
            return None
        got = await get_analysis(session, itinerary_id=fork_id, analysis_id=completed.id)
        findings = list(got[1]) if got is not None else []
    if any(fnd.severity is FindingSeverity.block for fnd in findings):
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="fork_infeasible")
    return None


async def _copy_starts_at(session: AsyncSession, *, src: uuid.UUID, dst: uuid.UUID) -> None:
    """Copy the ORM-invisible ``starts_at`` tstzrange from one node to another."""
    await session.execute(
        text(
            "update public.nodes d set starts_at = s.starts_at "
            "from public.nodes s where s.id = :src and d.id = :dst"
        ),
        {"src": src, "dst": dst},
    )
    await session.commit()


async def _set_parent_subgraph(
    session: AsyncSession, *, node_id: uuid.UUID, parent_id: uuid.UUID | None
) -> None:
    """Re-parent a node (``parent_subgraph_id`` is outside ``update_node``'s
    whitelist, so reconcile applies a subgraph move with a direct write)."""
    await session.execute(
        text("update public.nodes set parent_subgraph_id = :p where id = :n"),
        {"p": parent_id, "n": node_id},
    )
    await session.commit()


def _ok(change: NodeChange, detail: str | None = None) -> ReconcileOutcome:
    return ReconcileOutcome(
        change_id=change.change_id, kind=change.kind, result="applied", detail=detail
    )


def _refused(change: NodeChange) -> ReconcileOutcome:
    return ReconcileOutcome(
        change_id=change.change_id,
        kind=change.kind,
        result="refused_booked",
        detail="status_locked",
    )


def _failed(change: NodeChange, detail: str | None) -> ReconcileOutcome:
    return ReconcileOutcome(
        change_id=change.change_id, kind=change.kind, result="failed", detail=detail
    )


async def _apply_added(
    session: AsyncSession,
    actor: ActorContext,
    *,
    baseline_id: uuid.UUID,
    baseline_by_id: dict[uuid.UUID, NodeOut],
    change: NodeChange,
) -> ReconcileOutcome:
    """Fold an added fork node into the baseline as a native node (no lineage)."""
    assert change.fork_node_id is not None
    fork_node = (
        await session.execute(select(Node).where(Node.id == change.fork_node_id))
    ).scalar_one_or_none()
    if fork_node is None:
        return _failed(change, "fork_node_gone")
    # Map the parent onto the baseline if the fork parent's origin is a live
    # baseline node; otherwise the copy lands at top level.
    parent_id: uuid.UUID | None = None
    if fork_node.parent_subgraph_id is not None:
        parent_fork = (
            await session.execute(select(Node).where(Node.id == fork_node.parent_subgraph_id))
        ).scalar_one_or_none()
        if (
            parent_fork is not None
            and parent_fork.forked_from_node_id is not None
            and parent_fork.forked_from_node_id in baseline_by_id
        ):
            parent_id = parent_fork.forked_from_node_id
    new = await add_node(
        session,
        actor,
        itinerary_id=baseline_id,
        type=fork_node.type,
        status=fork_node.status,
        title=fork_node.title,
        parent_subgraph_id=parent_id,
        source=fork_node.source,
        source_id=fork_node.source_id,
        metadata=dict(fork_node.metadata_ or {}),
        cost_amount=fork_node.cost_amount,
        cost_currency=fork_node.cost_currency,
        cost_kind=fork_node.cost_kind,
    )
    if isinstance(new, ItineraryError):
        return _failed(change, new.detail)
    await _copy_starts_at(session, src=fork_node.id, dst=new.id)
    return _ok(change, str(new.id))


async def _apply_changed(
    session: AsyncSession,
    actor: ActorContext,
    *,
    baseline_id: uuid.UUID,
    baseline_by_id: dict[uuid.UUID, NodeOut],
    change: NodeChange,
) -> ReconcileOutcome:
    """Apply a fork node's content edits onto its live baseline node.

    Booked/confirmed baseline nodes are refused (G1 — never changed via
    reconcile). An approved baseline node is first demoted to ``pending`` (the
    advisor's pure G1 status change) so the edit lands; the traveler re-approves
    via the normal flow.
    """
    assert change.baseline_node_id is not None and change.fork_node_id is not None
    baseline_node = baseline_by_id.get(change.baseline_node_id)
    if baseline_node is None:
        return _failed(change, "baseline_node_gone")
    if baseline_node.status in (NodeStatus.booked, NodeStatus.confirmed):
        return _refused(change)
    fork_node = (
        await session.execute(select(Node).where(Node.id == change.fork_node_id))
    ).scalar_one_or_none()
    if fork_node is None:
        return _failed(change, "fork_node_gone")

    if baseline_node.status is NodeStatus.approved:
        demoted = await update_node(
            session,
            actor,
            itinerary_id=baseline_id,
            node_id=change.baseline_node_id,
            status=NodeStatus.pending,
        )
        if isinstance(demoted, ItineraryError):
            return _failed(change, demoted.detail)

    content: dict[str, Any] = {}
    for field in change.fields:
        if field not in _RECONCILABLE_CONTENT:
            continue
        if field == "metadata":
            content["metadata"] = dict(fork_node.metadata_ or {})
        else:
            content[field] = getattr(fork_node, field)
    if content:
        res = await update_node(
            session,
            actor,
            itinerary_id=baseline_id,
            node_id=change.baseline_node_id,
            **content,
        )
        if isinstance(res, ItineraryError):
            if res.outcome is ItineraryOutcome.STATUS_LOCKED:
                return _refused(change)
            return _failed(change, res.detail)
    if "starts_at" in change.fields:
        await _copy_starts_at(session, src=fork_node.id, dst=change.baseline_node_id)
    return _ok(change)


async def _apply_moved(
    session: AsyncSession,
    actor: ActorContext,
    *,
    baseline_id: uuid.UUID,
    baseline_by_id: dict[uuid.UUID, NodeOut],
    baseline_edges: list[Any],
    target_pred: uuid.UUID | None,
    target_succ: uuid.UUID | None,
    target_parent: uuid.UUID | None,
    change: NodeChange,
) -> ReconcileOutcome:
    """Re-wire the baseline ``follows`` edges + subgraph parent of the moved node.

    Rewires the moved node's own predecessor/successor to match the fork's mapped
    position, and re-parents it when the move changed its ``parent_subgraph_id``
    (a firmed baseline node is refused — never restructured via reconcile; an
    unresolvable target parent is left as-is). Neighbour-chain repair (healing a
    pre-existing P→S edge when a node moves out from between them) stays a
    follow-on — see the slice notes.
    """
    assert change.baseline_node_id is not None
    b_id = change.baseline_node_id
    if b_id in (target_pred, target_succ):
        return _failed(change, "move_cycle")
    for edge in baseline_edges:
        if edge.type is EdgeType.follows and (edge.from_node_id == b_id or edge.to_node_id == b_id):
            err = await delete_edge(session, actor, itinerary_id=baseline_id, edge_id=edge.id)
            if isinstance(err, ItineraryError):
                return _failed(change, err.detail)
    if target_pred is not None and target_pred in baseline_by_id:
        res = await add_edge(
            session,
            actor,
            itinerary_id=baseline_id,
            from_node_id=target_pred,
            to_node_id=b_id,
            type=EdgeType.follows,
        )
        if isinstance(res, ItineraryError):
            return _failed(change, res.detail)
    if target_succ is not None and target_succ in baseline_by_id:
        res = await add_edge(
            session,
            actor,
            itinerary_id=baseline_id,
            from_node_id=b_id,
            to_node_id=target_succ,
            type=EdgeType.follows,
        )
        if isinstance(res, ItineraryError):
            return _failed(change, res.detail)

    # Re-parent if the move changed the node's subgraph parent (mapped through
    # lineage). A firmed baseline node is refused (G1); a target parent that
    # doesn't resolve to a baseline node (it's new in the fork) is left as-is.
    baseline_node = baseline_by_id.get(b_id)
    current_parent = baseline_node.parent_subgraph_id if baseline_node is not None else None
    if target_parent != current_parent:
        if baseline_node is not None and baseline_node.status in (
            NodeStatus.booked,
            NodeStatus.confirmed,
        ):
            return _refused(change)
        if target_parent is None or target_parent in baseline_by_id:
            await _set_parent_subgraph(session, node_id=b_id, parent_id=target_parent)
    return _ok(change)


def _fold_trip_metadata(baseline: Itinerary, fork: Itinerary) -> None:
    """Fill unset trunk trip-level fields from the fork on publish.

    The reconcile diff only ever covers NODES; the trip's own title / brief /
    timing live on the itinerary row and would otherwise never reach the trunk.
    For a solo traveler — who builds entirely in their private fork — that
    leaves the published trunk blank ("Your itinerary" with no dates). So on
    every reconcile we copy each trip-level field from the fork into the trunk,
    but ONLY where the trunk's own value is still unset: an advisor who has
    curated the trunk's title/brief/window keeps it, and we never overwrite it
    with the fork's (which may still be the auto-generated ``"… (fork)"``
    placeholder). Timing is a coupled block (kind + window + anchor), so it
    copies whole-or-not-at-all keyed off the trunk having no timing_kind.
    """
    auto_title = f"{baseline.title} (fork)"
    if (
        not (baseline.title or "").strip()
        and (fork.title or "").strip()
        and fork.title != auto_title
    ):
        baseline.title = fork.title
    if baseline.brief is None and fork.brief is not None:
        baseline.brief = fork.brief
    if baseline.timing_kind is None and fork.timing_kind is not None:
        baseline.timing_kind = fork.timing_kind
        baseline.date_start = fork.date_start
        baseline.date_end = fork.date_end
        baseline.duration_nights = fork.duration_nights
        baseline.timing_note = fork.timing_note
        baseline.days_anchor = fork.days_anchor


async def reconcile_fork(
    session: AsyncSession,
    actor: ActorContext,
    *,
    fork_id: uuid.UUID,
    decisions: list[ReconcileDecision],
    analysis_id: uuid.UUID | None = None,
    override_block: bool = False,
    accept_all: bool = False,
) -> ReconcileResult | ItineraryError:
    """Fold the *accepted* fork changes into the live baseline (advisor-only).

    Mutates the baseline through the same ``update_node`` / ``delete_node`` /
    ``add_node`` path the rest of the app uses, so the G1 status gate keeps
    booked/confirmed nodes immutable (refused per-change, batch continues).
    A ``block``-severity Analyze finding on the fork refuses the whole pass
    unless ``override_block``. The fork flips to ``reconciled`` only when every
    diff change was decided and none was refused/failed; otherwise it stays
    ``open`` (honest partial). The pending reconcile request is always cleared.

    ``accept_all=True`` is the publish fast path: every change in the diff is
    accepted as computed *server-side in this same transaction*, so there is
    no staleness window between a client-fetched diff and the decisions it
    sends back. ``decisions`` is ignored (send ``[]``).
    """
    fork_itin = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one_or_none()
    if fork_itin is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if fork_itin.forked_from_id is None:
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="not_a_fork")
    baseline_id = fork_itin.forked_from_id

    block_err = await _feasibility_block(
        session, fork_id=fork_id, analysis_id=analysis_id, override_block=override_block
    )
    if block_err is not None:
        return block_err

    diff = await diff_fork(session, fork_id=fork_id)
    if isinstance(diff, ItineraryError):
        return diff
    change_map = {c.change_id: c for c in (*diff.added, *diff.removed, *diff.changed, *diff.moved)}
    if accept_all:
        decisions = [
            ReconcileDecision(change_id=change_id, accept=True) for change_id in change_map
        ]

    baseline_view = await get_itinerary_graph(session, baseline_id)
    if isinstance(baseline_view, ItineraryError):
        return baseline_view
    baseline_by_id = {n.id: n for n in baseline_view.nodes}
    baseline_edges = list(baseline_view.edges)
    # Position targets for moved changes, mapped through the fork's lineage.
    fork_view = await get_itinerary_graph(session, fork_id)
    if isinstance(fork_view, ItineraryError):
        return fork_view
    fork_to_origin = {n.id: n.forked_from_node_id for n in fork_view.nodes}
    fork_by_id = {n.id: n for n in fork_view.nodes}
    f_pred, f_succ = _follows_neighbors(fork_view)

    outcomes: list[ReconcileOutcome] = []
    for decision in decisions:
        change = change_map.get(decision.change_id)
        if change is None:
            outcomes.append(
                ReconcileOutcome(
                    change_id=decision.change_id,
                    kind="unknown",
                    result="skipped",
                    detail="stale_change",
                )
            )
            continue
        if not decision.accept:
            outcomes.append(
                ReconcileOutcome(change_id=change.change_id, kind=change.kind, result="discarded")
            )
            continue
        if change.kind == "added":
            outcome = await _apply_added(
                session,
                actor,
                baseline_id=baseline_id,
                baseline_by_id=baseline_by_id,
                change=change,
            )
        elif change.kind == "removed":
            assert change.baseline_node_id is not None
            err = await delete_node(
                session, actor, itinerary_id=baseline_id, node_id=change.baseline_node_id
            )
            if err is None:
                outcome = _ok(change)
            elif err.outcome is ItineraryOutcome.STATUS_LOCKED:
                outcome = _refused(change)
            else:
                outcome = _failed(change, err.detail)
        elif change.kind == "changed":
            outcome = await _apply_changed(
                session,
                actor,
                baseline_id=baseline_id,
                baseline_by_id=baseline_by_id,
                change=change,
            )
        else:  # moved
            assert change.fork_node_id is not None
            target_pred = fork_to_origin.get(f_pred.get(change.fork_node_id))  # type: ignore[arg-type]
            target_succ = fork_to_origin.get(f_succ.get(change.fork_node_id))  # type: ignore[arg-type]
            fork_node = fork_by_id.get(change.fork_node_id)
            target_parent = (
                fork_to_origin.get(fork_node.parent_subgraph_id)
                if fork_node is not None and fork_node.parent_subgraph_id is not None
                else None
            )
            outcome = await _apply_moved(
                session,
                actor,
                baseline_id=baseline_id,
                baseline_by_id=baseline_by_id,
                baseline_edges=baseline_edges,
                target_pred=target_pred,
                target_succ=target_succ,
                target_parent=target_parent,
                change=change,
            )
        outcomes.append(outcome)

    decided = {d.change_id for d in decisions}
    all_covered = set(change_map).issubset(decided)
    unresolved = any(o.result in ("refused_booked", "failed") for o in outcomes)

    fork_row = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one()
    baseline_row = (
        await session.execute(select(Itinerary).where(Itinerary.id == baseline_id))
    ).scalar_one()
    if all_covered and not unresolved:
        fork_row.fork_status = ForkStatus.reconciled
    fork_row.reconcile_requested_at = None
    fork_row.reconcile_request_note = None
    # Publish the fork's trip-level title/brief/timing onto the trunk (the diff
    # only carries node changes), filling any trunk field the traveler's working
    # copy owns but the trunk never had.
    _fold_trip_metadata(baseline_row, fork_row)
    await session.commit()
    await session.refresh(fork_row)
    await session.refresh(baseline_row)

    logger.info(
        "fork.reconcile",
        extra={
            "fork_id": str(fork_id),
            "baseline_id": str(baseline_id),
            "applied": sum(1 for o in outcomes if o.result == "applied"),
            "discarded": sum(1 for o in outcomes if o.result == "discarded"),
            "refused": sum(1 for o in outcomes if o.result == "refused_booked"),
            "fork_status": fork_row.fork_status.value if fork_row.fork_status else None,
            "actor_kind": actor.kind.value,
        },
    )
    return ReconcileResult(itinerary=baseline_row, fork=fork_row, outcomes=outcomes)


async def request_reconcile(
    session: AsyncSession,
    actor: ActorContext,
    *,
    fork_id: uuid.UUID,
    note: str | None = None,
) -> Itinerary | ItineraryError:
    """Stamp a traveler/agent request that staff merge this fork. Idempotent."""
    fork_itin = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one_or_none()
    if fork_itin is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if fork_itin.forked_from_id is None:
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="not_a_fork")
    stmt = (
        update(Itinerary)
        .where(Itinerary.id == fork_id)
        .values(reconcile_requested_at=func.now(), reconcile_request_note=note)
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    await session.refresh(row)
    logger.info(
        "fork.request_reconcile",
        extra={
            "fork_id": str(fork_id),
            "has_note": note is not None,
            "actor_kind": actor.kind.value,
        },
    )
    return row


async def withdraw_reconcile(
    session: AsyncSession,
    actor: ActorContext,
    *,
    fork_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Clear a pending reconcile request WITHOUT abandoning the fork. Idempotent.

    The inverse of :func:`request_reconcile`: the traveler asked staff to merge,
    then changed their mind. ``fork_status`` stays ``open`` so they keep editing
    their alternative; only the request stamp + note are cleared.
    """
    fork_itin = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one_or_none()
    if fork_itin is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if fork_itin.forked_from_id is None:
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="not_a_fork")
    stmt = (
        update(Itinerary)
        .where(Itinerary.id == fork_id)
        .values(reconcile_requested_at=None, reconcile_request_note=None)
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    await session.refresh(row)
    logger.info(
        "fork.withdraw_reconcile",
        extra={"fork_id": str(fork_id), "actor_kind": actor.kind.value},
    )
    return row


async def abandon_fork(
    session: AsyncSession,
    actor: ActorContext,
    *,
    fork_id: uuid.UUID,
) -> Itinerary | ItineraryError:
    """Mark a fork ``abandoned`` and clear any pending reconcile request."""
    fork_itin = (
        await session.execute(select(Itinerary).where(Itinerary.id == fork_id))
    ).scalar_one_or_none()
    if fork_itin is None:
        return ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    if fork_itin.forked_from_id is None:
        return ItineraryError(outcome=ItineraryOutcome.VALIDATION_ERROR, detail="not_a_fork")
    stmt = (
        update(Itinerary)
        .where(Itinerary.id == fork_id)
        .values(
            fork_status=ForkStatus.abandoned,
            reconcile_requested_at=None,
            reconcile_request_note=None,
        )
        .returning(Itinerary)
        .execution_options(synchronize_session="fetch")
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    await session.refresh(row)
    logger.info("fork.abandon", extra={"fork_id": str(fork_id), "actor_kind": actor.kind.value})
    return row
