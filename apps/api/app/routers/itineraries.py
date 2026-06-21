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
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.db import get_session, get_sessionmaker
from app.models import (
    Client,
    EdgeType,
    ItineraryStatus,
    NodeStatus,
    NodeType,
    Profile,
    UserRole,
)
from app.services.agent import drain_queue
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    _serialize_starts_at,
    _tz_offset_from_metadata,
    acquire_lock,
    add_edge,
    add_node,
    approve_itinerary,
    assemble_initial_draft,
    create_itinerary,
    delete_edge,
    delete_node,
    get_itinerary_graph,
    release_lock,
    update_node,
)
from app.inventory.registry import InventoryCtx, UnknownSourceError
from app.routers.inventory import get_inventory_registry
from app.services.card_mapping import inventory_item_to_card_metadata
from app.services.inventory import get_inventory_detail

if TYPE_CHECKING:
    from app.inventory.registry import InventoryProviderRegistry
    from sqlalchemy.ext.asyncio import AsyncSession


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


class CreateNodeRequest(BaseModel):
    type: NodeType
    status: NodeStatus = NodeStatus.idea
    title: str = ""
    parent_subgraph_id: uuid.UUID | None = None
    source: str | None = None
    source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    # Scheduled timing, derived from the node's ``starts_at`` tstzrange.
    # ``starts_at`` is the ISO-8601 lower bound; ``duration_minutes`` is the
    # whole-minute span (upper - lower), or None when there is no upper bound
    # (or no range at all). Both are None for nodes without a schedule.
    starts_at: str | None = None
    duration_minutes: int | None = None
    depth: int | None = None


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
    return ActorContext(
        user_id=user_uuid, kind=ActorKind.ADVISOR, actor_id=user.sub
    )


async def _resolve_client_auth_user_id(
    session: "AsyncSession", client_id: uuid.UUID
) -> uuid.UUID | None:
    """Return the ``auth.users.id`` for the client, or None if missing.

    Extracted as a helper so the owner check on the draft-read gate can
    be monkey-patched by route-level tests that stub the DB session.
    """
    return (
        await session.execute(
            select(Client.auth_user_id).where(Client.id == client_id)
        )
    ).scalar_one_or_none()


async def _is_requester_advisor(
    session: "AsyncSession", user_uuid: uuid.UUID | None
) -> bool:
    """One-shot profile lookup used by the draft-read gate.

    Returns ``True`` iff ``user_uuid`` is non-null and the profiles row for
    that id carries ``role = 'advisor'``. Low-RPS by design — the itinerary
    read endpoint lives off the hot path, so a single SELECT per call is
    cheap next to the recursive graph CTE.
    """
    if user_uuid is None:
        return False
    row = (
        await session.execute(
            select(Profile.role).where(Profile.id == user_uuid)
        )
    ).scalar_one_or_none()
    return row is UserRole.advisor


# ── Outcome mapping ────────────────────────────────────────────────────────


def _raise_for_error(err: ItineraryError) -> None:
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
    # Defensive — every enum value is mapped above.
    logger.error(
        "itinerary.router.unhandled_outcome", extra={"outcome": err.outcome.value}
    )
    raise HTTPException(status_code=500, detail="internal_error")


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
    session: "AsyncSession" = Depends(get_session),
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
    session: "AsyncSession" = Depends(get_session),
) -> GraphResponse:
    result = await get_itinerary_graph(session, itinerary_id)
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    # Draft-read gate: on status='draft', only advisors, the owning client,
    # or the creator of the itinerary may read the graph. Everyone else
    # gets a 403 with detail='forbidden' so the client-side SDK can
    # discriminate deterministically. The agent acting on the client's
    # behalf carries the client's JWT, so the same ``is_owner`` branch
    # admits it without a separate actor_kind check.
    itinerary_row = result.itinerary
    if itinerary_row.status is ItineraryStatus.draft:
        actor = _actor_from_user(user)
        # ``is_owner`` compares the caller's auth.users id against the
        # clients row linked to this itinerary — clients.id and
        # auth.users.id live in different UUID namespaces, so resolve via
        # clients.auth_user_id rather than comparing directly.
        is_owner = False
        if actor.user_id is not None and itinerary_row.client_id is not None:
            owning_auth_user_id = await _resolve_client_auth_user_id(
                session, itinerary_row.client_id
            )
            is_owner = (
                owning_auth_user_id is not None
                and owning_auth_user_id == actor.user_id
            )
        is_creator = (
            actor.user_id is not None
            and itinerary_row.created_by is not None
            and actor.user_id == itinerary_row.created_by
        )
        if not (is_owner or is_creator):
            is_advisor = await _is_requester_advisor(session, actor.user_id)
            if not is_advisor:
                logger.info(
                    "itinerary.draft_access_denied",
                    extra={
                        "sub_hint": (user.sub or "")[:8],
                        "itinerary_id": str(itinerary_id),
                    },
                )
                raise HTTPException(status_code=403, detail="forbidden")
    # mypy: result is GraphView past this point
    return GraphResponse(
        itinerary=ItineraryResponse(
            id=result.itinerary.id,
            title=result.itinerary.title,
            client_id=result.itinerary.client_id,
            created_by=result.itinerary.created_by,
            status=result.itinerary.status or ItineraryStatus.draft,
            approved_by=result.itinerary.approved_by,
            approved_at=result.itinerary.approved_at,
        ),
        nodes=[
            NodeResponse(
                id=n.id,
                itinerary_id=n.itinerary_id,
                parent_subgraph_id=n.parent_subgraph_id,
                type=n.type,
                status=n.status,
                title=n.title,
                source=n.source,
                source_id=n.source_id,
                metadata=n.metadata,
                starts_at=n.starts_at,
                duration_minutes=n.duration_minutes,
                depth=n.depth,
            )
            for n in result.nodes
        ],
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
    "/{itinerary_id}/nodes",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeResponse,
    summary="Insert a node into an itinerary graph.",
)
async def create_node_endpoint(
    itinerary_id: uuid.UUID,
    payload: CreateNodeRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> NodeResponse:
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
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    starts_at, duration_minutes = _serialize_starts_at(
        result.starts_at, _tz_offset_from_metadata(result.metadata_)
    )
    return NodeResponse(
        id=result.id,
        itinerary_id=result.itinerary_id,
        parent_subgraph_id=result.parent_subgraph_id,
        type=result.type,
        status=result.status,
        title=result.title,
        source=result.source,
        source_id=result.source_id,
        metadata=result.metadata_,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
    )


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
    session: "AsyncSession" = Depends(get_session),
    registry: "InventoryProviderRegistry" = Depends(get_inventory_registry),
) -> NodeResponse:
    """Fetch the item, derive its card metadata, and add it as a node.

    The provider lookup is the single source of card semantics: a Duffel
    flight becomes a ``flight`` node carrying ``FlightCardAttrs`` (cabin /
    seat / depart-arrive), a Ratehawk stay a ``hotel`` node, etc. Goes
    through the same ``add_node`` write path as a hand-built node, so the
    lock/queue + history invariants are unchanged.
    """
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
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    starts_at, duration_minutes = _serialize_starts_at(
        result.starts_at, _tz_offset_from_metadata(result.metadata_)
    )
    return NodeResponse(
        id=result.id,
        itinerary_id=result.itinerary_id,
        parent_subgraph_id=result.parent_subgraph_id,
        type=result.type,
        status=result.status,
        title=result.title,
        source=result.source,
        source_id=result.source_id,
        metadata=result.metadata_,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
    )


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
    session: "AsyncSession" = Depends(get_session),
) -> NodeResponse:
    actor = _actor_from_user(user)
    # Only forward fields the client actually set so "omitted" ≠ "set to None".
    fields = payload.model_dump(exclude_unset=True)
    result = await update_node(
        session, actor, itinerary_id=itinerary_id, node_id=node_id, **fields
    )
    if isinstance(result, ItineraryError):
        _raise_for_error(result)
    starts_at, duration_minutes = _serialize_starts_at(
        result.starts_at, _tz_offset_from_metadata(result.metadata_)
    )
    return NodeResponse(
        id=result.id,
        itinerary_id=result.itinerary_id,
        parent_subgraph_id=result.parent_subgraph_id,
        type=result.type,
        status=result.status,
        title=result.title,
        source=result.source,
        source_id=result.source_id,
        metadata=result.metadata_,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
    )


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
    session: "AsyncSession" = Depends(get_session),
) -> Response:
    actor = _actor_from_user(user)
    err = await delete_node(
        session, actor, itinerary_id=itinerary_id, node_id=node_id
    )
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
    )


@router.post(
    "/{itinerary_id}/lock",
    response_model=ItineraryResponse,
    summary="Acquire the advisor editor lock on an itinerary.",
)
async def lock_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: "AsyncSession" = Depends(get_session),
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
    session: "AsyncSession" = Depends(get_session),
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
    session: "AsyncSession" = Depends(get_session),
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
    "/{itinerary_id}/assemble",
    response_model=GraphResponse,
    summary="Assemble the initial draft by wiring follows edges across days.",
)
async def assemble_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    payload: AssembleDraftRequest,
    user: AuthenticatedUser = Depends(require_user),
    session: "AsyncSession" = Depends(get_session),
) -> GraphResponse:
    # Gate by role: advisors stamp ADVISOR, anyone else stamps USER. The
    # service layer's lock gate admits both ADVISOR (always) and the lock
    # holder (same user_id), so an advisor-assembled draft during their own
    # lock still goes through without queueing.
    actor = _actor_from_user(user)
    if await _is_requester_advisor(session, actor.user_id):
        actor = _advisor_actor_from_user(user)
    day_plan = [
        {
            "day_index": slot.day_index,
            "node_ids_in_order": slot.node_ids_in_order,
        }
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
        nodes=[
            NodeResponse(
                id=n.id,
                itinerary_id=n.itinerary_id,
                parent_subgraph_id=n.parent_subgraph_id,
                type=n.type,
                status=n.status,
                title=n.title,
                source=n.source,
                source_id=n.source_id,
                metadata=n.metadata,
                starts_at=n.starts_at,
                duration_minutes=n.duration_minutes,
                depth=n.depth,
            )
            for n in result.nodes
        ],
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
    session: "AsyncSession" = Depends(get_session),
) -> EdgeResponse:
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
    session: "AsyncSession" = Depends(get_session),
) -> Response:
    actor = _actor_from_user(user)
    err = await delete_edge(
        session, actor, itinerary_id=itinerary_id, edge_id=edge_id
    )
    if err is not None:
        _raise_for_error(err)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
