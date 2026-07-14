"""Mt Olympus campaign spine builder — length-variant templates.

Turns the :mod:`app.seed_data.olympus_itinerary` day-list into three
``card_templates`` subgraphs — 5, 7, and 14 nights — by taking the first *N*
days of the (prefix-coherent) fixture. Each is idempotent via
``find_or_create_template`` + ``has_subgraph``, so building on every cold start
is a no-op after the first.

The kickoff (``POST /itinerary/{id}/campaign/kickoff``) snaps the traveler's
chosen nights to one of these lengths and instantiates the matching template
onto their fork with :func:`app.services.templates.instantiate_into`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CardTemplate, EdgeType, NodeStatus, NodeType
from app.seed_data.japan_itinerary import FixtureItem
from app.seed_data.olympus_cornerstones import (
    CORNERSTONE_ANCHOR_ID_HINT,
    OlympusCornerstone,
    cornerstone_for_nights,
)
from app.seed_data.olympus_itinerary import OLYMPUS_DAYS, TRIP_ANCHOR
from app.services.subgraph import day_subgraph_metadata
from app.services.templates import (
    add_template_edge,
    add_template_node,
    find_or_create_template,
    has_subgraph,
)

logger = logging.getLogger("ov_black.templates.olympus")

#: nights → template slug, mirrored by app.campaigns.registry OLYMPUS.
OLYMPUS_SPINE_SLUGS: dict[int, str] = {5: "olympus-5d", 7: "olympus-7d", 14: "olympus-14d"}


def _offset_minutes(starts_at: datetime) -> int:
    return int((starts_at - TRIP_ANCHOR).total_seconds() // 60)


def _node_type_for(item: FixtureItem) -> NodeType:
    return NodeType(item.attrs.kind)


async def _build_cornerstone_subgraph(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    parent_id: uuid.UUID,
    cornerstone: OlympusCornerstone,
) -> tuple[int, int]:
    """Add the cornerstone's day-by-day itinerary as ``parent_id``'s children.

    Mirrors :func:`app.services.subgraph.materialize_day_subgraph` in template
    space: one ``experience`` child per OV day (``Day N — title``, unscheduled,
    ``day_subgraph_metadata`` shape) chained by ``follows`` edges. Returns
    ``(node_count, edge_count)`` added. No-op (0, 0) when the cornerstone ships
    no baked days.
    """
    node_count = 0
    edge_count = 0
    previous: uuid.UUID | None = None
    for day in cornerstone.itinerary_days():
        child = await add_template_node(
            session,
            template_id=template_id,
            type=NodeType.experience,
            title=f"Day {day.day} — {day.title}",
            parent_id=parent_id,
            metadata=day_subgraph_metadata(day),
        )
        node_count += 1
        if previous is not None:
            await add_template_edge(
                session,
                template_id=template_id,
                from_template_node_id=previous,
                to_template_node_id=child.id,
                type=EdgeType.follows,
                metadata={"reason": "day_sequence"},
            )
            edge_count += 1
        previous = child.id
    return node_count, edge_count


async def build_olympus_template(session: AsyncSession, *, nights: int) -> CardTemplate:
    """Find-or-create the ``nights``-length Olympus spine + populate its subgraph.

    ``nights`` must be one of :data:`OLYMPUS_SPINE_SLUGS`. The spine is the first
    ``nights`` days of the shared fixture, wired with within-day + day-to-day
    ``follows`` edges exactly like the Japan builder. The summit node is enriched
    with the length's real OV cornerstone trip (cover, gallery, description,
    price) — see :mod:`app.seed_data.olympus_cornerstones`.
    """
    slug = OLYMPUS_SPINE_SLUGS.get(nights)
    if slug is None:
        raise ValueError(f"unsupported Olympus spine length: {nights}")

    # Real OV trip this spine is built around — the longest spine anchors on the
    # full "Path to Symbolism" ascent, the shorter ones on the 2-day summit push.
    # Its cover + gallery + price enrich the summit node so the demo shows genuine
    # Olympus photography behind the curated skeleton.
    cornerstone = cornerstone_for_nights(nights, longest=max(OLYMPUS_SPINE_SLUGS))

    template, created = await find_or_create_template(
        session,
        slug=slug,
        name=f"Mount Olympus · {nights} nights",
        description=(
            f"Curated {nights}-night Mt Olympus / Greece spine — Litochoro base, "
            "Enipeas gorge, the Spilios Agapitos refuge, and the Mytikas summit."
        ),
        metadata={
            "trip_anchor_iso": TRIP_ANCHOR.isoformat(),
            "campaign_id": "olympus",
            "nights": nights,
        },
    )
    if not created and await has_subgraph(session, template_id=template.id):
        logger.info(
            "templates.olympus.skip_rebuild",
            extra={"template_id": str(template.id), "slug": slug, "nights": nights},
        )
        return template

    last_of_previous_day: uuid.UUID | None = None
    total_nodes = 0
    total_edges = 0

    for day in OLYMPUS_DAYS[:nights]:
        prev_in_day: uuid.UUID | None = None
        first_in_day: uuid.UUID | None = None
        for item in day.items:
            metadata = item.attrs.model_dump(mode="json", exclude_none=True)
            # The summit node is the spine's cornerstone: fold in the real OV
            # trip's cover (hero), gallery, description, and price.
            if item.id_hint == CORNERSTONE_ANCHOR_ID_HINT:
                metadata.update(cornerstone.enrichment())
            utcoffset = item.starts_at.utcoffset()
            if utcoffset is not None:
                metadata["tz_offset_minutes"] = int(utcoffset.total_seconds() // 60)
            metadata["_seed_status"] = NodeStatus(item.status).value
            tnode = await add_template_node(
                session,
                template_id=template.id,
                type=_node_type_for(item),
                title=item.title,
                starts_at_offset_minutes=_offset_minutes(item.starts_at),
                duration_minutes=item.duration_minutes,
                metadata=metadata,
            )
            total_nodes += 1
            # The cornerstone anchor is a real multi-day OV adventure — lay its
            # day-by-day itinerary down as this node's SUBGRAPH (children carry
            # ``parent_id`` = the anchor; ``instantiate_into`` clones that as
            # ``parent_subgraph_id`` on the fork). The card then reads as the
            # bookable OV trip it is: an expandable day-by-day journey, not a
            # single photo. Children are unscheduled + provenance-free and
            # chained by ``follows`` — identical to the from-inventory path.
            if item.id_hint == CORNERSTONE_ANCHOR_ID_HINT:
                n, e = await _build_cornerstone_subgraph(
                    session, template_id=template.id, parent_id=tnode.id, cornerstone=cornerstone
                )
                total_nodes += n
                total_edges += e
            if first_in_day is None:
                first_in_day = tnode.id
            if prev_in_day is not None:
                await add_template_edge(
                    session,
                    template_id=template.id,
                    from_template_node_id=prev_in_day,
                    to_template_node_id=tnode.id,
                    type=EdgeType.follows,
                )
                total_edges += 1
            prev_in_day = tnode.id

        if last_of_previous_day is not None and first_in_day is not None:
            await add_template_edge(
                session,
                template_id=template.id,
                from_template_node_id=last_of_previous_day,
                to_template_node_id=first_in_day,
                type=EdgeType.follows,
            )
            total_edges += 1
        last_of_previous_day = prev_in_day

    await session.commit()
    logger.info(
        "templates.olympus.built",
        extra={
            "template_id": str(template.id),
            "slug": slug,
            "nights": nights,
            "node_count": total_nodes,
            "edge_count": total_edges,
        },
    )
    return template


__all__ = ["OLYMPUS_SPINE_SLUGS", "build_olympus_template"]
