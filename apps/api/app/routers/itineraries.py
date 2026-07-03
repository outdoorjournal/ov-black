"""Itinerary graph HTTP surface (M001/S02).

Seven endpoints:

- ``POST   /itinerary``                              create a graph
- ``GET    /itinerary/{id}``                         assembled graph view
- ``POST   /itinerary/{id}/nodes``                   insert a node
- ``PATCH  /itinerary/{id}/nodes/{node_id}``         update a node
- ``DELETE /itinerary/{id}/nodes/{node_id}``         delete a node
- ``POST   /itinerary/{id}/edges``                   insert an edge
- ``DELETE /itinerary/{id}/edges/{edge_id}``         delete an edge

All of them sit behind the JWT middleware; ``AuthenticatedUser`` is pulled via
``require_user`` and mapped into an :class:`ActorContext` with
``kind=USER``. Service outcomes are mapped to HTTP status codes here; the
service never raises.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session, get_sessionmaker
from app.inventory.registry import InventoryCtx, UnknownSourceError
from app.models import (
    Client,
    CostKind,
    EdgeType,
    ForkStatus,
    Itinerary,
    ItineraryStatus,
    NodeStatus,
    NodeType,
    Profile,
    UserRole,
)
from app.routers.inventory import get_inventory_registry
from app.services.agent import drain_queue
from app.services.card_mapping import inventory_item_to_card_metadata
from app.services.fork import (
    ForkDiff,
    NodeChange,
    ReconcileDecision,
    ReconcileResult,
    abandon_fork,
    diff_fork,
    fork_itinerary,
    reconcile_fork,
    request_reconcile,
    withdraw_reconcile,
)
from app.services.inventory import get_inventory_detail
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    DaySlot,
    ItineraryError,
    ItineraryOutcome,
    _serialize_starts_at,
    _tz_offset_from_metadata,
    acquire_lock,
    add_edge,
    add_node,
    approve_itinerary,
    assemble_initial_draft,
    compute_lock_reason,
    create_itinerary,
    delete_edge,
    delete_node,
    get_itinerary_graph,
    release_lock,
    update_node,
)
from app.services.node_cost import cost_from_inventory_item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.inventory.registry import InventoryProviderRegistry


logger = logging.getLogger("ov_black.routers.itineraries")

router = APIRouter(prefix="/itinerary", tags=["itinerary"])


# ── Request / response models ──────────────────────────────────────────────


class CreateItineraryRequest(BaseModel):
    title: str = Field(default="", max_length=512)
    client_id: uuid.UUID | None = None


class ItineraryResponse(BaseModel):
    id: uuid.UUID
    title: str
    client_id: uuid.UUID | None
    created_by: uuid.UUID | None
    status: ItineraryStatus = ItineraryStatus.draft
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    # Fork lineage (G2). ``forked_from_id`` is the baseline this itinerary was
    # cloned from (None on a normal itinerary); ``fork_status`` tracks the
    # reconcile lifecycle and is None unless this row is a fork.
    forked_from_id: uuid.UUID | None = None
    fork_status: ForkStatus | None = None
    # Reconcile request (G3). Set when a traveler/agent asks staff to merge this
    # fork; cleared on reconcile/abandon. None on a fork with no pending request.
    reconcile_requested_at: datetime | None = None
    reconcile_request_note: str | None = None


class CreateNodeRequest(BaseModel):
    type: NodeType
    status: NodeStatus = NodeStatus.idea
    title: str = ""
    parent_subgraph_id: uuid.UUID | None = None
    source: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # First-class cost (D-COST). amount + currency must be set together.
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None
    # Note anchoring (0014). A `note` is dual-mode: set `attached_to_node_id` to
    # annotate a host node, OR `starts_at` (ISO-8601, + optional
    # `duration_minutes`) for a free-standing note — exactly one. Ignored for
    # non-note types (and `attached_to_node_id` is rejected on them).
    attached_to_node_id: uuid.UUID | None = None
    starts_at: str | None = None
    duration_minutes: int | None = None


class CreateNodeFromInventoryRequest(BaseModel):
    """Create a graph node from a live inventory item by (source, source_id).

    The server fetches the current item through the provider registry and
    derives the typed card metadata (e.g. a Duffel flight → FlightCardAttrs),
    so callers never hand-shape card attrs. For flights this re-fetch is a
    natural offer refresh (D024). ``status`` defaults to ``proposed`` — the
    item is a candidate on the board, not a stray idea.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    source_id: str
    status: NodeStatus = NodeStatus.proposed
    parent_subgraph_id: uuid.UUID | None = None


class UpdateNodeRequest(BaseModel):
    """Partial update. Any field omitted is left unchanged.

    ``model_config`` uses ``extra="forbid"`` so a misspelled field surfaces
    as 422, not a silent no-op.
    """

    model_config = ConfigDict(extra="forbid")

    type: NodeType | None = None
    status: NodeStatus | None = None
    title: str | None = None
    source: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] | None = None
    # First-class cost (D-COST). Advisor edits land here; amount + currency
    # must be set/cleared together (service-layer + DB CHECK enforce it).
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None


class NodeResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    parent_subgraph_id: uuid.UUID | None
    type: NodeType
    status: NodeStatus
    title: str
    source: str | None
    source_id: str | None
    metadata: dict[str, Any]
    # First-class node cost (D-COST). ``cost_amount`` is a native-currency
    # decimal (serialized as a JSON string to avoid float precision loss);
    # ``cost_currency`` is ISO 4217; ``cost_kind`` is per_person|total. All
    # None for a node without a cost.
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    cost_kind: CostKind | None = None
    # Scheduled timing, derived from the node's ``starts_at`` tstzrange.
    # ``starts_at`` is the ISO-8601 lower bound; ``duration_minutes`` is the
    # whole-minute span (upper - lower), or None when there is no upper bound
    # (or no range at all). Both are None for nodes without a schedule.
    starts_at: str | None = None
    duration_minutes: int | None = None
    depth: int | None = None
    # Computed mutation-lock reason (G1). ``"status_locked"`` when the node is
    # firmed (approved/booked/confirmed), else None. Lets the agent/web explain
    # a refused edit without re-deriving the rule client-side.
    lock_reason: str | None = None
    # Fork lineage (G2). The baseline node this one was copied from, or None.
    forked_from_node_id: uuid.UUID | None = None
    # Note attachment (0014). For a `note` riding a host node, the host's id;
    # None for a free-standing note (which carries `starts_at`) or any non-note.
    attached_to_node_id: uuid.UUID | None = None


class CreateEdgeRequest(BaseModel):
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    id: uuid.UUID
    itinerary_id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    type: EdgeType
    metadata: dict[str, Any]


class GraphResponse(BaseModel):
    itinerary: ItineraryResponse
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    # The calling viewer's own OPEN fork of this itinerary, when it is a baseline
    # (``forked_from_id is None``) — the traveler's "My version". Resolved per
    # request in ``get_itinerary_endpoint`` so the two-version toggle switches to
    # an existing fork instead of spawning a duplicate. Null on a fork itself, or
    # when the viewer has no open fork.
    viewer_open_fork_id: uuid.UUID | None = None


class ReleaseLockResponse(BaseModel):
    itinerary: ItineraryResponse
    replayed_count: int


class DaySlotPayload(BaseModel):
    """One day's ordered node ids for the assemble_initial_draft route."""

    model_config = ConfigDict(extra="forbid")

    day_index: int
    node_ids_in_order: list[uuid.UUID]


class AssembleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_plan: list[DaySlotPayload] = Field(default_factory=list)


class ForkItineraryRequest(BaseModel):
    """Fork an itinerary into a versioned clone (G2). ``title`` defaults to
    ``"{baseline} (fork)"`` when omitted."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=512)


# ── G3 fork diff / reconcile ────────────────────────────────────────────────


class NodeChangeResponse(BaseModel):
    """One divergence in a fork's diff (added/removed/changed/moved).

    ``change_id`` is the stable handle the reconcile request references in its
    decisions. ``before`` is the baseline snapshot, ``after`` the fork snapshot
    (one is null for added/removed). ``fields`` names the changed content fields
    (plus ``"position"`` when a content change also moved).
    """

    change_id: uuid.UUID
    kind: str
    fork_node_id: uuid.UUID | None = None
    baseline_node_id: uuid.UUID | None = None
    fields: list[str] = Field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class ForkDiffResponse(BaseModel):
    fork_id: uuid.UUID
    baseline_id: uuid.UUID
    added: list[NodeChangeResponse]
    removed: list[NodeChangeResponse]
    changed: list[NodeChangeResponse]
    moved: list[NodeChangeResponse]


class ReconcileDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: uuid.UUID
    accept: bool


class ReconcileRequest(BaseModel):
    """Advisor per-change accept/discard verdicts, with the feasibility gate.

    ``analysis_id`` pins which Analyze run gates the pass (defaults to the fork's
    latest completed run); ``override_block`` is the advisor's explicit, logged
    escape hatch past a ``block`` finding.
    """

    model_config = ConfigDict(extra="forbid")

    decisions: list[ReconcileDecisionPayload] = Field(default_factory=list)
    analysis_id: uuid.UUID | None = None
    override_block: bool = False


class ReconcileOutcomeResponse(BaseModel):
    """What happened to one decided change: applied / discarded / refused_booked
    / failed / skipped (see ``services.fork.ReconcileOutcome``)."""

    change_id: uuid.UUID
    kind: str
    result: str
    detail: str | None = None


class ReconcileResponse(BaseModel):
    """The post-reconcile live baseline graph + the fork + per-change outcomes."""

    baseline: GraphResponse
    fork: ItineraryResponse
    outcomes: list[ReconcileOutcomeResponse]


class RequestReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


# ── Actor resolution ────────────────────────────────────────────────────────


def _actor_from_user(user: AuthenticatedUser) -> ActorContext:
    """Map a Supabase-authenticated user to an ActorContext.

    ``user.sub`` is a UUID string from Supabase Auth. We parse it here so a
    malformed sub surfaces as 401 at the middleware layer rather than a 500
    inside the service; if parsing fails the actor is still recorded but
    with ``user_id=None``.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except (ValueError, AttributeError):
        user_uuid = None
    return ActorContext(user_id=user_uuid, kind=ActorKind.USER, actor_id=user.sub)


def _advisor_actor_from_user(user: AuthenticatedUser) -> ActorContext:
    """Same as :func:`_actor_from_user` but stamps ``kind=ADVISOR``.

    Used from the lock / release / approve / assemble routes, which are
    already gated by ``require_advisor``. Writing AGENT-layer history rows
    from these handlers would be a lie — the caller is an advisor, and the
    service layer uses the actor kind to decide whether to bypass the lock
    gate.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except (ValueError, AttributeError):
        user_uuid = None
    return ActorContext(user_id=user_uuid, kind=ActorKind.ADVISOR, actor_id=user.sub)


async def _load_itinerary(session: AsyncSession, itinerary_id: uuid.UUID) -> Itinerary | None:
    """Load an itinerary row by id (or None). Extracted so the fork endpoint's
    authz pre-load can be monkeypatched by route-level tests that stub the DB."""
    return (
        await session.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()


async def _resolve_client_auth_user_id(
    session: AsyncSession, client_id: uuid.UUID
) -> uuid.UUID | None:
    """Return the ``auth.users.id`` for the client, or None if missing.

    Extracted as a helper so the owner check on the draft-read gate can
    be monkey-patched by route-level tests that stub the DB session.
    """
    return (
        await session.execute(select(Client.auth_user_id).where(Client.id == client_id))
    ).scalar_one_or_none()


async def _resolve_viewer_open_fork_id(
    session: AsyncSession,
    user: AuthenticatedUser,
    *,
    baseline_id: uuid.UUID,
) -> uuid.UUID | None:
    """The caller's own OPEN fork of ``baseline_id`` (their "My version"), or None.

    A fork is stamped with ``created_by = actor.user_id`` (see ``fork_itinerary``),
    so the traveler's own working copy is the open fork they created off this
    baseline. Picks the most-recent so any pre-existing duplicate forks (from the
    old "Make an alternative" flow) still resolve to one entry; the lazy-fork model
    stops new duplicates being created.
    """
    try:
        user_uuid = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        return None
    return (
        await session.execute(
            select(Itinerary.id)
            .where(
                Itinerary.forked_from_id == baseline_id,
                Itinerary.fork_status == ForkStatus.open,
                Itinerary.created_by == user_uuid,
            )
            .order_by(Itinerary.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _is_requester_advisor(session: AsyncSession, user_uuid: uuid.UUID | None) -> bool:
    """One-shot profile lookup used by the draft-read gate.

    Returns ``True`` iff ``user_uuid`` is non-null and the profiles row for
    that id carries ``role = 'advisor'``. Low-RPS by design — the itinerary
    read endpoint lives off the hot path, so a single SELECT per call is
    cheap next to the recursive graph CTE.
    """
    if user_uuid is None:
        return False
    row = (
        await session.execute(select(Profile.role).where(Profile.id == user_uuid))
    ).scalar_one_or_none()
    return row is UserRole.advisor


async def assert_itinerary_readable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Draft-read gate, shared by the graph-read and analyze endpoints.

    On ``status='draft'`` only advisors, the owning client, or the creator may
    read; everyone else gets a 403 with ``detail='forbidden'`` so the SDK can
    discriminate deterministically. The agent acting on the client's behalf
    carries the client's JWT, so the ``is_owner`` branch admits it without a
    separate actor_kind check. Approved itineraries are readable by any
    authenticated user. ``itinerary`` must expose ``status`` / ``client_id`` /
    ``created_by`` / ``id``.
    """
    if itinerary.status is not ItineraryStatus.draft:
        return
    actor = _actor_from_user(user)
    # ``is_owner`` compares the caller's auth.users id against the clients row
    # linked to this itinerary — clients.id and auth.users.id live in different
    # UUID namespaces, so resolve via clients.auth_user_id.
    is_owner = False
    if actor.user_id is not None and itinerary.client_id is not None:
        owning_auth_user_id = await _resolve_client_auth_user_id(session, itinerary.client_id)
        is_owner = owning_auth_user_id is not None and owning_auth_user_id == actor.user_id
    is_creator = (
        actor.user_id is not None
        and itinerary.created_by is not None
        and actor.user_id == itinerary.created_by
    )
    if is_owner or is_creator:
        return
    if await _is_requester_advisor(session, actor.user_id):
        return
    logger.info(
        "itinerary.draft_access_denied",
        extra={
            "sub_hint": (user.sub or "")[:8],
            "itinerary_id": str(itinerary.id),
        },
    )
    raise HTTPException(status_code=403, detail="forbidden")


async def _has_write_relationship(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> bool:
    """True iff the caller may mutate (or fork) this itinerary.

    The write relationship is **owner** (the client's auth user, resolved via
    ``clients.auth_user_id`` since ``clients.id`` and ``auth.users.id`` live in
    different namespaces) **or creator** (``created_by`` — which is what
    readmits the agent to a concierge-created draft whose ``client_id`` is still
    null) **or advisor**. ``itinerary`` must expose ``client_id`` / ``created_by``.
    """
    actor = _actor_from_user(user)
    if actor.user_id is not None and itinerary.client_id is not None:
        owning_auth_user_id = await _resolve_client_auth_user_id(session, itinerary.client_id)
        if owning_auth_user_id is not None and owning_auth_user_id == actor.user_id:
            return True
    if (
        actor.user_id is not None
        and itinerary.created_by is not None
        and actor.user_id == itinerary.created_by
    ):
        return True
    return await _is_requester_advisor(session, actor.user_id)


async def assert_itinerary_forkable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Only the owning client, the creator, or an advisor may fork an itinerary.

    Stricter than the draft-read gate (which admits any authenticated user to an
    *approved* itinerary): a fork writes a brand-new itinerary onto the client, so
    we require a real relationship to the baseline regardless of its status. The
    agent acting for the client carries the client's JWT, so the owner branch
    admits it. 403 ``forbidden`` so the SDK discriminates deterministically.
    """
    if await _has_write_relationship(session, user, itinerary):
        return
    logger.info(
        "itinerary.fork_denied",
        extra={"sub_hint": (user.sub or "")[:8], "itinerary_id": str(itinerary.id)},
    )
    raise HTTPException(status_code=403, detail="forbidden")


async def assert_itinerary_writable(
    session: AsyncSession,
    user: AuthenticatedUser,
    itinerary: Any,
) -> None:
    """Gate node/edge writes: only the owner, creator, or an advisor may mutate.

    Closes the gap where any authenticated user holding an itinerary id could
    write to any unlocked, non-firmed graph. Shares the fork gate's relationship
    test (:func:`_has_write_relationship`), so the agent — carrying the client's
    JWT — is admitted as owner, or as creator on a concierge-created draft whose
    ``client_id`` is still null. 403 ``forbidden`` so the SDK discriminates
    deterministically.
    """
    if await _has_write_relationship(session, user, itinerary):
        return
    logger.info(
        "itinerary.write_denied",
        extra={"sub_hint": (user.sub or "")[:8], "itinerary_id": str(itinerary.id)},
    )
    raise HTTPException(status_code=403, detail="forbidden")


# ── Outcome mapping ────────────────────────────────────────────────────────


def _raise_for_error(err: ItineraryError) -> NoReturn:
    """Map an ItineraryError to the conventional HTTPException."""
    if err.outcome is ItineraryOutcome.NOT_FOUND:
        raise HTTPException(status_code=404, detail="not_found")
    if err.outcome is ItineraryOutcome.INVALID_PROVENANCE:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "invalid_provenance",
        )
    if err.outcome is ItineraryOutcome.INVALID_PARENT:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "invalid_parent",
        )
    if err.outcome is ItineraryOutcome.VALIDATION_ERROR:
        raise HTTPException(
            status_code=400,
            detail=err.detail or "validation_error",
        )
    if err.outcome is ItineraryOutcome.FORBIDDEN:
        raise HTTPException(status_code=403, detail=err.detail or "forbidden")
    if err.outcome is ItineraryOutcome.LOCKED:
        raise HTTPException(status_code=409, detail=err.detail or "already_locked")
    if err.outcome is ItineraryOutcome.STATUS_LOCKED:
        # The node's lifecycle status forbids this mutation (G1). 409 like the
        # editor lock; the detail token (status_locked / demote_before_edit /
        # demote_before_delete) lets the agent + web craft the human reason.
        raise HTTPException(status_code=409, detail=err.detail or "status_locked")
    if err.outcome is ItineraryOutcome.CONFLICT:
        # A precondition on related state failed — e.g. the M005 money gate: a
        # node can't be flipped straight to booked/confirmed via update_node
        # (that authority is services.bookings). 409 so the caller can tell
        # "not allowed yet" from a 400; the detail token (use_booking_flow, …)
        # lets the agent + web craft the human reason.
        raise HTTPException(status_code=409, detail=err.detail or "conflict")
    # Defensive — every enum value is mapped above.
    logger.error("itinerary.router.unhandled_outcome", extra={"outcome": err.outcome.value})
    raise HTTPException(status_code=500, detail="internal_error")


# ── Node response builders ──────────────────────────────────────────────────


def _node_response_from_out(n: Any) -> NodeResponse:
    """Build a NodeResponse from a service ``NodeOut`` (graph-read shape).

    ``NodeOut`` already carries the serialized ``starts_at`` / cost fields, so
    this is a straight field copy. Used by the graph-read + assemble endpoints.
    """
    return NodeResponse(
        id=n.id,
        itinerary_id=n.itinerary_id,
        parent_subgraph_id=n.parent_subgraph_id,
        type=n.type,
        status=n.status,
        title=n.title,
        source=n.source,
        source_id=n.source_id,
        metadata=n.metadata,
        cost_amount=n.cost_amount,
        cost_currency=n.cost_currency,
        cost_kind=n.cost_kind,
        starts_at=n.starts_at,
        duration_minutes=n.duration_minutes,
        depth=n.depth,
        lock_reason=n.lock_reason,
        forked_from_node_id=n.forked_from_node_id,
        attached_to_node_id=n.attached_to_node_id,
    )


def _node_response_from_node(node: Any) -> NodeResponse:
    """Build a NodeResponse from a persisted ``Node`` ORM row (write shape).

    The single-node write endpoints (create / update / from-inventory) return
    a ``Node`` whose ``starts_at`` is still a raw tstzrange, so it's serialized
    here with the node's recorded local offset.
    """
    starts_at, duration_minutes = _serialize_starts_at(
        node.starts_at, _tz_offset_from_metadata(node.metadata_)
    )
    return NodeResponse(
        id=node.id,
        itinerary_id=node.itinerary_id,
        parent_subgraph_id=node.parent_subgraph_id,
        type=node.type,
        status=node.status,
        title=node.title,
        source=node.source,
        source_id=node.source_id,
        metadata=node.metadata_,
        cost_amount=node.cost_amount,
        cost_currency=node.cost_currency,
        cost_kind=node.cost_kind,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        lock_reason=compute_lock_reason(node.status),
        forked_from_node_id=getattr(node, "forked_from_node_id", None),
        attached_to_node_id=getattr(node, "attached_to_node_id", None),
    )


def _graph_to_response(view: Any) -> GraphResponse:
    """Assemble a GraphResponse from a service GraphView (itinerary + nodes + edges).

    Shared by the graph-read and fork endpoints so fork lineage (on the itinerary
    and every node) serializes identically everywhere.
    """
    return GraphResponse(
        itinerary=_itinerary_to_response(view.itinerary),
        nodes=[_node_response_from_out(n) for n in view.nodes],
        edges=[
            EdgeResponse(
                id=e.id,
                itinerary_id=e.itinerary_id,
                from_node_id=e.from_node_id,
                to_node_id=e.to_node_id,
                type=e.type,
                metadata=e.metadata,
            )
            for e in view.edges
        ],
    )


def _node_change_response(change: NodeChange) -> NodeChangeResponse:
    return NodeChangeResponse(
        change_id=change.change_id,
        kind=change.kind,
        fork_node_id=change.fork_node_id,
        baseline_node_id=change.baseline_node_id,
        fields=list(change.fields),
        before=change.before,
        after=change.after,
    )


def _fork_diff_response(diff: ForkDiff) -> ForkDiffResponse:
    return ForkDiffResponse(
        fork_id=diff.fork_id,
        baseline_id=diff.baseline_id,
        added=[_node_change_response(c) for c in diff.added],
        removed=[_node_change_response(c) for c in diff.removed],
        changed=[_node_change_response(c) for c in diff.changed],
        moved=[_node_change_response(c) for c in diff.moved],
    )


def _reconcile_response(result: ReconcileResult, baseline_view: Any) -> ReconcileResponse:
    return ReconcileResponse(
        baseline=_graph_to_response(baseline_view),
        fork=_itinerary_to_response(result.fork),
        outcomes=[
            ReconcileOutcomeResponse(
                change_id=o.change_id, kind=o.kind, result=o.result, detail=o.detail
            )
            for o in result.outcomes
        ],
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ItineraryResponse,
    summary="Create a new itinerary graph.",
)
async def create_itinerary_endpoint(
    payload: CreateItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    actor = _actor_from_user(user)
    itinerary = await create_itinerary(
        session, actor, title=payload.title, client_id=payload.client_id
    )
    return ItineraryResponse(
        id=itinerary.id,
        title=itinerary.title,
        client_id=itinerary.client_id,
        created_by=itinerary.created_by,
        status=itinerary.status or ItineraryStatus.draft,
        approved_by=itinerary.approved_by,
        approved_at=itinerary.approved_at,
    )


@router.get(
    "/{itinerary_id}",
    response_model=GraphResponse,
    summary="Get the assembled itinerary graph.",
)
async def get_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    result = await get_itinerary_graph(session, itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    # Draft-read gate (shared with the analyze endpoints).
    await assert_itinerary_readable(session, user, result.itinerary)
    # mypy: result is GraphView past this point
    response = _graph_to_response(result)
    # On a baseline, surface the caller's own OPEN fork so the traveler's
    # two-version toggle ("My version") resolves to it rather than re-forking.
    if result.itinerary.forked_from_id is None:
        response.viewer_open_fork_id = await _resolve_viewer_open_fork_id(
            session, user, baseline_id=itinerary_id
        )
    return response


@router.post(
    "/{itinerary_id}/nodes",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Insert a node into an itinerary graph.",
)
async def create_node_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=payload.type,
        status=payload.status,
        title=payload.title,
        parent_subgraph_id=payload.parent_subgraph_id,
        source=payload.source,
        source_id=payload.source_id,
        metadata=payload.metadata,
        cost_amount=payload.cost_amount,
        cost_currency=payload.cost_currency,
        cost_kind=payload.cost_kind,
        attached_to_node_id=payload.attached_to_node_id,
        starts_at=payload.starts_at,
        duration_minutes=payload.duration_minutes,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result)


@router.post(
    "/{itinerary_id}/nodes/from-inventory",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Create a node from a live inventory item (typed card metadata).",
)
async def create_node_from_inventory_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeFromInventoryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    registry: InventoryProviderRegistry = Depends(get_inventory_registry),
) -> NodeResponse:
    """Fetch the item, derive its card metadata, and add it as a node.

    The provider lookup is the single source of card semantics: a Duffel
    flight becomes a ``flight`` node carrying ``FlightCardAttrs`` (cabin /
    seat / depart-arrive), a Ratehawk stay a ``hotel`` node, etc. Goes
    through the same ``add_node`` write path as a hand-built node, so the
    lock/queue + history invariants are unchanged.
    """
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    ctx = InventoryCtx(actor_kind="user", actor_id=user.sub)
    try:
        item = await get_inventory_detail(
            registry, source=payload.source, source_id=payload.source_id, ctx=ctx
        )
    except UnknownSourceError as exc:
        logger.info("itinerary.from_inventory.unknown_source", extra={"source": exc.source})
        raise HTTPException(status_code=400, detail="unknown_source") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="inventory_not_found")

    # ``InventoryItem.kind`` is a 1:1 subset of NodeType (flight, hotel, meal,
    # experience, destination, transit, note); guard so an unmapped kind is a
    # clean 422 rather than a 500 deep in add_node.
    try:
        node_type = NodeType(item.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unmappable_inventory_kind") from exc

    metadata = inventory_item_to_card_metadata(item)
    # Promote the provider's price to first-class cost columns (B4 / D-COST):
    # a Duffel flight or Ratehawk hotel lands with a queryable numeric cost,
    # not just a snapshot string. ``None`` for a price-less item (e.g. a
    # Google-Places meal) — the node simply carries no cost.
    cost = cost_from_inventory_item(item)
    result = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=node_type,
        status=payload.status,
        title=item.title,
        parent_subgraph_id=payload.parent_subgraph_id,
        source=item.source,
        source_id=item.source_id,
        metadata=metadata,
        cost_amount=cost.amount if cost else None,
        cost_currency=cost.currency if cost else None,
        cost_kind=cost.kind if cost else None,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result)


@router.patch(
    "/{itinerary_id}/nodes/{node_id}",
    response_model=NodeResponse,
    summary="Update a node (partial).",
)
async def update_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    payload: UpdateNodeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> NodeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    # Resolve actor kind so the status gate (G1) can tell an advisor (who may
    # demote/cancel a firmed node) from a traveler/agent (who cannot). The
    # agent carries the client's JWT, so it resolves to USER like a traveler.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    # Only forward fields the client actually set so "omitted" ≠ "set to None".
    fields = payload.model_dump(exclude_unset=True)
    result = await update_node(session, actor, itinerary_id=itinerary_id, node_id=node_id, **fields)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _node_response_from_node(result)


@router.delete(
    "/{itinerary_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a node.",
)
async def delete_node_endpoint(
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    # See update_node_endpoint: advisor resolution drives the G1 status gate.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    err = await delete_node(session, actor, itinerary_id=itinerary_id, node_id=node_id)
    if err is not None:
        _raise_for_error(err)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _itinerary_to_response(itinerary: Any) -> ItineraryResponse:
    return ItineraryResponse(
        id=itinerary.id,
        title=itinerary.title,
        client_id=itinerary.client_id,
        created_by=itinerary.created_by,
        status=itinerary.status or ItineraryStatus.draft,
        approved_by=itinerary.approved_by,
        approved_at=itinerary.approved_at,
        forked_from_id=getattr(itinerary, "forked_from_id", None),
        fork_status=getattr(itinerary, "fork_status", None),
        reconcile_requested_at=getattr(itinerary, "reconcile_requested_at", None),
        reconcile_request_note=getattr(itinerary, "reconcile_request_note", None),
    )


@router.post(
    "/{itinerary_id}/lock",
    response_model=ItineraryResponse,
    summary="Acquire the advisor editor lock on an itinerary.",
)
async def lock_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    actor = _advisor_actor_from_user(user)
    result = await acquire_lock(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/release",
    response_model=ReleaseLockResponse,
    summary="Release the advisor editor lock and drain the agent write queue.",
)
async def release_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ReleaseLockResponse:
    actor = _advisor_actor_from_user(user)
    result = await release_lock(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    # Drain happens after the lock row has been cleared. The agent queue
    # lives in-process (D008), so we grab the same sessionmaker the request
    # uses; each queued entry opens a fresh session for its replay.
    replayed = await drain_queue(get_sessionmaker(), itinerary_id)
    return ReleaseLockResponse(
        itinerary=_itinerary_to_response(result),
        replayed_count=replayed,
    )


@router.post(
    "/{itinerary_id}/approve",
    response_model=ItineraryResponse,
    summary="Approve the itinerary — flips status draft→approved.",
)
async def approve_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    actor = _advisor_actor_from_user(user)
    result = await approve_itinerary(session, actor, itinerary_id=itinerary_id)
    if isinstance(result, ItineraryError):
        # VALIDATION_ERROR with detail='already_approved' should surface as 409
        # per the slice contract, not the generic 400.
        if (
            result.outcome is ItineraryOutcome.VALIDATION_ERROR
            and result.detail == "already_approved"
        ):
            raise HTTPException(status_code=409, detail="already_approved")
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/fork",
    response_model=GraphResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fork an itinerary into an independently-editable versioned clone (G2).",
)
async def fork_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: ForkItineraryRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Deep-copy ``itinerary_id`` into a new fork and return the fork's graph.

    Traveler-initiated (and the agent, via the client's JWT). Pre-booked nodes
    copy in editable; booked/confirmed nodes copy in carried-locked (the G1 gate
    keeps them immutable in the fork). Every node carries ``forked_from_node_id``
    lineage; the itinerary carries ``forked_from_id``.
    """
    baseline = await _load_itinerary(session, itinerary_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, baseline)
    # Stamp the actor kind so the fork's history rows attribute correctly and a
    # later advisor edit on the fork resolves to ADVISOR (G1 gate).
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await fork_itinerary(session, actor, itinerary_id=itinerary_id, title=payload.title)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    view = await get_itinerary_graph(session, result.id)
    if isinstance(view, ItineraryError):
        _raise_for_error(view)
    return _graph_to_response(view)


@router.get(
    "/{fork_id}/diff",
    response_model=ForkDiffResponse,
    summary="Diff a fork against its baseline (added/removed/changed/moved).",
)
async def diff_fork_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ForkDiffResponse:
    """Pair a fork's nodes to their baseline origins by lineage and bucket the
    divergence. Owner / creator / advisor only (``assert_itinerary_forkable``)."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    result = await diff_fork(session, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _fork_diff_response(result)


@router.post(
    "/{fork_id}/reconcile",
    response_model=ReconcileResponse,
    summary="Fold accepted fork changes into the live baseline (advisor only).",
)
async def reconcile_fork_endpoint(
    fork_id: uuid.UUID,
    payload: ReconcileRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ReconcileResponse:
    """Apply each accepted change to the baseline through the lock/queue +
    status-gate path; booked nodes are refused per-change, not applied. Refuses
    the whole pass on a ``block`` Analyze finding unless ``override_block``.
    Advisor-only (``require_advisor`` + stamps ADVISOR)."""
    actor = _advisor_actor_from_user(user)
    decisions = [
        ReconcileDecision(change_id=d.change_id, accept=d.accept) for d in payload.decisions
    ]
    result = await reconcile_fork(
        session,
        actor,
        fork_id=fork_id,
        decisions=decisions,
        analysis_id=payload.analysis_id,
        override_block=payload.override_block,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    baseline_view = await get_itinerary_graph(session, result.itinerary.id)
    if isinstance(baseline_view, ItineraryError):
        _raise_for_error(baseline_view)
    return _reconcile_response(result, baseline_view)


@router.post(
    "/{fork_id}/request-reconcile",
    response_model=ItineraryResponse,
    summary="Ask staff to merge this fork (traveler/agent; advisor executes).",
)
async def request_reconcile_endpoint(
    fork_id: uuid.UUID,
    payload: RequestReconcileRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Stamp a pending reconcile request on the fork. Owner / creator / advisor;
    the traveler can request but only an advisor executes the merge."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await request_reconcile(session, actor, fork_id=fork_id, note=payload.note)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{fork_id}/cancel-reconcile",
    response_model=ItineraryResponse,
    summary="Withdraw a pending merge request (traveler/agent); the fork stays open.",
)
async def cancel_reconcile_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Clear the pending reconcile request on the fork without abandoning it.

    The inverse of ``request-reconcile``: the traveler asked staff to merge, then
    changed their mind. Owner / creator / advisor; the fork stays ``open`` so they
    keep editing."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await withdraw_reconcile(session, actor, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{fork_id}/abandon",
    response_model=ItineraryResponse,
    summary="Abandon a fork without merging (advisor or owner).",
)
async def abandon_fork_endpoint(
    fork_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> ItineraryResponse:
    """Mark the fork ``abandoned`` and clear any pending reconcile request."""
    fork = await _load_itinerary(session, fork_id)
    if fork is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_forkable(session, user, fork)
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    result = await abandon_fork(session, actor, fork_id=fork_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return _itinerary_to_response(result)


@router.post(
    "/{itinerary_id}/assemble",
    response_model=GraphResponse,
    summary="Assemble the initial draft by wiring follows edges across days.",
)
async def assemble_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: AssembleDraftRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> GraphResponse:
    # Gate by role: advisors stamp ADVISOR, anyone else stamps USER. The
    # service layer's lock gate admits both ADVISOR (always) and the lock
    # holder (same user_id), so an advisor-assembled draft during their own
    # lock still goes through without queueing.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    day_plan: list[DaySlot] = [
        DaySlot(
            day_index=slot.day_index,
            node_ids_in_order=slot.node_ids_in_order,
        )
        for slot in payload.day_plan
    ]
    result = await assemble_initial_draft(
        session,
        actor,
        itinerary_id=itinerary_id,
        day_plan=day_plan,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return GraphResponse(
        itinerary=_itinerary_to_response(result.itinerary),
        nodes=[_node_response_from_out(n) for n in result.nodes],
        edges=[
            EdgeResponse(
                id=e.id,
                itinerary_id=e.itinerary_id,
                from_node_id=e.from_node_id,
                to_node_id=e.to_node_id,
                type=e.type,
                metadata=e.metadata,
            )
            for e in result.edges
        ],
    )


@router.post(
    "/{itinerary_id}/edges",
    status_code=status.HTTP_201_CREATED,
    response_model=EdgeResponse,
    summary="Insert an edge into an itinerary graph.",
)
async def create_edge_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateEdgeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> EdgeResponse:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    result = await add_edge(
        session,
        actor,
        itinerary_id=itinerary_id,
        from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id,
        type=payload.type,
        metadata=payload.metadata,
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    return EdgeResponse(
        id=result.id,
        itinerary_id=result.itinerary_id,
        from_node_id=result.from_node_id,
        to_node_id=result.to_node_id,
        type=result.type,
        metadata=result.metadata_,
    )


@router.delete(
    "/{itinerary_id}/edges/{edge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an edge.",
)
async def delete_edge_endpoint(
    itinerary_id: uuid.UUID,
    edge_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_writable(session, user, itinerary)
    actor = _actor_from_user(user)
    err = await delete_edge(session, actor, itinerary_id=itinerary_id, edge_id=edge_id)
    if err is not None:
        _raise_for_error(err)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
