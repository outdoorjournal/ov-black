"""Card-template service — TravelGraph Phase 4.

Two responsibilities:

1. **Authoring** — create / lookup-by-slug / extend a template's
   subgraph by adding template_nodes + template_edges. The
   ``find_or_create`` helper is what the seed-data builders use to
   make their templates idempotent: rerunning the same builder
   returns the existing template instead of duplicating it.

2. **Instantiation** — copy every template_node + template_edge into
   a new itinerary's nodes / edges, anchoring relative offsets at a
   concrete ``trip_start_at``. Each new node carries the template
   lineage snapshot (``template_id`` + ``template_node_id`` +
   ``template_version``) so a later drift detector can flag updates
   without comparing every field.

The instantiation walks the template subgraph in topological order so
parent + attached-host references resolve to fresh node ids before
their children are inserted.

History rows: instantiation does NOT write to ``node_history`` /
``edge_history`` per row. The lineage of an instantiated subgraph is
captured by the snapshot columns; surfacing every row's insert as
"actor=template" would just churn the timeline. A single advisor
"instantiated template X" event can land in a future audit table if
needed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CardTemplate,
    Edge,
    EdgeType,
    Itinerary,
    ItineraryStatus,
    NodeRole,
    NodeStatus,
    NodeType,
    TemplateEdge,
    TemplateNode,
)

logger = logging.getLogger("ov_black.templates")


# ── Authoring ─────────────────────────────────────────────────────────


async def find_or_create_template(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    description: str = "",
    owner_advisor_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[CardTemplate, bool]:
    """Look up a template by slug, creating one if it doesn't exist.

    Returns ``(template, created)``. Idempotent — seed-data builders
    call this so reruns don't duplicate.
    """
    existing = (
        await session.execute(select(CardTemplate).where(CardTemplate.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    template = CardTemplate(
        slug=slug,
        name=name,
        description=description,
        owner_advisor_id=owner_advisor_id,
        metadata_=metadata or {},
    )
    session.add(template)
    await session.flush()
    await session.commit()
    logger.info(
        "templates.create",
        extra={"template_id": str(template.id), "slug": slug},
    )
    return template, True


async def add_template_node(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    type: NodeType,
    title: str = "",
    parent_id: uuid.UUID | None = None,
    attached_to_template_node_id: uuid.UUID | None = None,
    role: NodeRole | None = None,
    starts_at_offset_minutes: int | None = None,
    duration_minutes: int | None = None,
    altitude_m: int | None = None,
    is_selected_alt: bool = True,
    metadata: dict[str, Any] | None = None,
) -> TemplateNode:
    """Insert a TemplateNode under ``template_id``."""
    node = TemplateNode(
        template_id=template_id,
        parent_id=parent_id,
        attached_to_template_node_id=attached_to_template_node_id,
        type=type,
        role=role,
        title=title,
        starts_at_offset_minutes=starts_at_offset_minutes,
        duration_minutes=duration_minutes,
        altitude_m=altitude_m,
        is_selected_alt=is_selected_alt,
        metadata_=metadata or {},
    )
    session.add(node)
    await session.flush()
    return node


async def add_template_edge(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    from_template_node_id: uuid.UUID,
    to_template_node_id: uuid.UUID,
    type: EdgeType,
    metadata: dict[str, Any] | None = None,
) -> TemplateEdge:
    edge = TemplateEdge(
        template_id=template_id,
        from_template_node_id=from_template_node_id,
        to_template_node_id=to_template_node_id,
        type=type,
        metadata_=metadata or {},
    )
    session.add(edge)
    await session.flush()
    return edge


async def has_subgraph(session: AsyncSession, *, template_id: uuid.UUID) -> bool:
    """Quick check used by seed builders: does this template already
    have any nodes? Lets the builder no-op the costly subgraph step
    on rerun.
    """
    return (
        await session.execute(
            select(TemplateNode.id).where(TemplateNode.template_id == template_id).limit(1)
        )
    ).scalar_one_or_none() is not None


# ── Instantiation ─────────────────────────────────────────────────────


def _starts_at_lower_upper(
    *,
    trip_start_at: datetime,
    offset_minutes: int | None,
    duration_minutes: int | None,
) -> tuple[datetime | None, datetime | None]:
    """Convert a TemplateNode's relative offset + duration to absolute
    range bounds. Returns ``(None, None)`` when the template node has
    no offset (e.g. attached notes) so the SQL CASE-emits a NULL
    tstzrange.
    """
    if offset_minutes is None:
        return None, None
    lower = trip_start_at + timedelta(minutes=offset_minutes)
    upper = lower + timedelta(minutes=duration_minutes) if duration_minutes is not None else lower
    return lower, upper


async def instantiate_template(
    session: AsyncSession,
    *,
    template: CardTemplate,
    client_id: uuid.UUID | None,
    trip_start_at: datetime,
    title: str | None = None,
    created_by: uuid.UUID | None = None,
) -> Itinerary:
    """Create a new Itinerary materialized from ``template`` at ``trip_start_at``.

    Walks the template subgraph in two passes so FK references resolve:

    1. Parents-first node insert — sort template_nodes by depth so a
       child's ``parent_id`` always finds its freshly-inserted parent.
       Same for attached notes (host always inserted first).
    2. Edge insert — every from/to template_node id maps to the new
       node id via the lookup built in pass (1).

    Each new node receives ``template_id`` + ``template_node_id`` +
    ``template_version`` snapshots so future drift checks can run
    without re-reading the template.
    """
    itinerary = Itinerary(
        title=title or template.name,
        client_id=client_id,
        created_by=created_by,
        status=ItineraryStatus.draft,
    )
    session.add(itinerary)
    await session.flush()

    # Load every template_node + edge in one round-trip each.
    template_nodes = (
        (await session.execute(select(TemplateNode).where(TemplateNode.template_id == template.id)))
        .scalars()
        .all()
    )
    template_edges = (
        (await session.execute(select(TemplateEdge).where(TemplateEdge.template_id == template.id)))
        .scalars()
        .all()
    )

    # Topological order: a node's parent or attached host must already
    # exist in the lookup before we insert it. The dependency graph is
    # parent_id ∪ attached_to_template_node_id; we BFS from roots.
    by_id = {tn.id: tn for tn in template_nodes}
    deps: dict[uuid.UUID, list[uuid.UUID]] = {tn.id: [] for tn in template_nodes}
    for tn in template_nodes:
        if tn.parent_id is not None:
            deps[tn.id].append(tn.parent_id)
        if tn.attached_to_template_node_id is not None:
            deps[tn.id].append(tn.attached_to_template_node_id)

    ordered: list[TemplateNode] = []
    placed: set[uuid.UUID] = set()
    while len(ordered) < len(template_nodes):
        progress = False
        for tn in template_nodes:
            if tn.id in placed:
                continue
            if all(dep in placed for dep in deps[tn.id]):
                ordered.append(tn)
                placed.add(tn.id)
                progress = True
        if not progress:
            # Cycle in template subgraph — should have been caught by the
            # template's CHECK constraints. Fail loudly so the template
            # author can fix the data; instantiation must not partially
            # succeed.
            raise RuntimeError(
                f"template {template.slug!r} has a cyclic parent/attached "
                f"dependency among template_nodes — cannot instantiate"
            )

    new_id_by_template_node: dict[uuid.UUID, uuid.UUID] = {}

    for tn in ordered:
        lower, upper = _starts_at_lower_upper(
            trip_start_at=trip_start_at,
            offset_minutes=tn.starts_at_offset_minutes,
            duration_minutes=tn.duration_minutes,
        )
        new_id = uuid.uuid4()
        new_id_by_template_node[tn.id] = new_id

        await session.execute(
            text(
                """
                insert into public.nodes (
                    id, itinerary_id, parent_subgraph_id, type, status,
                    title, metadata, role, is_selected_alt,
                    starts_at, altitude_m, attached_to_node_id,
                    template_id, template_node_id, template_version
                ) values (
                    :id, :iid,
                    cast(:parent as uuid),
                    cast(:type as public.node_type),
                    cast(:status as public.node_status),
                    :title,
                    cast(:meta as jsonb),
                    case when cast(:role as text) is null then null
                         else cast(:role as public.node_role) end,
                    :sel,
                    case when cast(:lo as timestamptz) is null
                          and cast(:hi as timestamptz) is null then null
                         else tstzrange(
                             cast(:lo as timestamptz),
                             cast(:hi as timestamptz),
                             '[)'
                         ) end,
                    :alt,
                    cast(:att as uuid),
                    :tpl_id,
                    :tpl_node_id,
                    :tpl_version
                )
                """
            ),
            {
                "id": new_id,
                "iid": itinerary.id,
                "parent": (
                    str(new_id_by_template_node[tn.parent_id]) if tn.parent_id is not None else None
                ),
                "type": tn.type.value,
                "status": NodeStatus.proposed.value,
                "title": tn.title,
                "meta": _to_json(tn.metadata_),
                "role": tn.role.value if tn.role is not None else None,
                "sel": tn.is_selected_alt,
                "lo": lower,
                "hi": upper,
                "alt": tn.altitude_m,
                "att": (
                    str(new_id_by_template_node[tn.attached_to_template_node_id])
                    if tn.attached_to_template_node_id is not None
                    else None
                ),
                "tpl_id": template.id,
                "tpl_node_id": tn.id,
                "tpl_version": template.version,
            },
        )

    for te in template_edges:
        edge = Edge(
            itinerary_id=itinerary.id,
            from_node_id=new_id_by_template_node[te.from_template_node_id],
            to_node_id=new_id_by_template_node[te.to_template_node_id],
            type=te.type,
            metadata_=te.metadata_,
        )
        session.add(edge)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise

    await session.commit()
    logger.info(
        "templates.instantiate",
        extra={
            "template_id": str(template.id),
            "slug": template.slug,
            "version": template.version,
            "itinerary_id": str(itinerary.id),
            "node_count": len(template_nodes),
            "edge_count": len(template_edges),
        },
    )
    # Re-load so callers see all server defaults.
    await session.refresh(itinerary)
    _ = by_id  # silence: kept for future debug paths
    return itinerary


def _to_json(value: dict[str, Any]) -> str:
    """Serialize a JSON-able dict for the raw SQL insert. asyncpg
    accepts a string when the column is cast to jsonb.
    """
    import json

    return json.dumps(value or {})


__all__ = [
    "add_template_edge",
    "add_template_node",
    "find_or_create_template",
    "has_subgraph",
    "instantiate_template",
]
