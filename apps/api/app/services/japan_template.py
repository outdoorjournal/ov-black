"""Japan trip template builder — TravelGraph Phase 4.

Wraps the seed-data Japan fixture into a real ``card_templates`` row
+ template subgraph the demo endpoint can instantiate into any
client's account. Idempotent — rerunning the builder against an
existing template returns the same row without rebuilding the
subgraph.

The fixture's items carry absolute datetimes (the original 2024 trip).
We anchor the template at ``2024-06-20T00:00 JST`` (start-of-day on
the original arrival date) and store every offset relative to that
anchor. Instantiation receives a fresh ``trip_start_at`` and shifts
every node accordingly, so the same template can re-launch any
calendar week.

Within each day we wire ``follows`` edges between consecutive items.
We also draw a day-to-day bridge from the last item of day N to the
first of day N+1. That mirrors the JS fixture's edge-building logic
and gives the linearization service something to walk.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CardTemplate, EdgeType, NodeType
from app.seed_data.japan_itinerary import JAPAN_DAYS, FixtureItem
from app.services.templates import (
    add_template_edge,
    add_template_node,
    find_or_create_template,
    has_subgraph,
)

logger = logging.getLogger("ov_black.templates.japan")

JAPAN_TEMPLATE_SLUG = "japan-2024-tokyo-kyoto"
JAPAN_TEMPLATE_NAME = "Japan · 15 days · Tokyo → Kyoto → Hiroshima → Osaka → Mt Fuji → Tokyo"
JAPAN_TEMPLATE_DESCRIPTION = (
    "Curated June 2024 multi-city Japan itinerary covering Tokyo "
    "(Tsukiji, Asakusa, Shinjuku), Kyoto (Arashiyama, Fushimi Inari), "
    "Hiroshima, Osaka, and Mt Fuji."
)

# Trip anchor — start-of-day on the original arrival date in JST.
JST = timezone(timedelta(hours=9))
TRIP_ANCHOR = datetime(2024, 6, 20, 0, 0, tzinfo=JST)


def _offset_minutes(starts_at: datetime) -> int:
    """Minutes from TRIP_ANCHOR. Uses the absolute-time of the fixture
    item; instantiation re-anchors at a fresh trip_start_at.
    """
    delta = starts_at - TRIP_ANCHOR
    return int(delta.total_seconds() // 60)


def _node_type_for(item: FixtureItem) -> NodeType:
    """Map the fixture item's ``attrs.kind`` (matches the Pydantic
    discriminator) onto the matching :class:`NodeType` enum value.
    """
    return NodeType(item.attrs.kind)


async def build_japan_template(session: AsyncSession) -> CardTemplate:
    """Find-or-create the Japan template + populate its subgraph.

    Returns the persisted ``CardTemplate`` row. Subsequent calls are
    no-ops once the subgraph exists, so this is safe to run on every
    cold start.
    """
    template, created = await find_or_create_template(
        session,
        slug=JAPAN_TEMPLATE_SLUG,
        name=JAPAN_TEMPLATE_NAME,
        description=JAPAN_TEMPLATE_DESCRIPTION,
        metadata={
            "trip_anchor_iso": TRIP_ANCHOR.isoformat(),
            "regions": ["Tokyo", "Kyoto", "Hiroshima", "Osaka", "Fuji"],
        },
    )
    if not created and await has_subgraph(session, template_id=template.id):
        logger.info(
            "templates.japan.skip_rebuild",
            extra={"template_id": str(template.id), "slug": template.slug},
        )
        return template

    # Build node-by-node, day-by-day. Track per-day first/last so we
    # can stitch within-day follows edges AND a day-to-day bridge from
    # the last node of day N to the first of day N+1.
    last_of_previous_day: uuid.UUID | None = None
    total_nodes = 0
    total_edges = 0

    for day in JAPAN_DAYS:
        prev_in_day: uuid.UUID | None = None
        first_in_day: uuid.UUID | None = None
        for item in day.items:
            metadata = item.attrs.model_dump(mode="json", exclude_none=True)
            # Stamp the item's local UTC offset (minutes) so the read side
            # can re-emit starts_at in wall-clock for this leg. A trip spans
            # multiple zones (LAX→Tokyo: departure PDT, everything after JST),
            # and the tstzrange column normalizes to UTC, losing the offset.
            utcoffset = item.starts_at.utcoffset()
            if utcoffset is not None:
                metadata["tz_offset_minutes"] = int(
                    utcoffset.total_seconds() // 60
                )
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

        # Bridge across the day boundary.
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
        "templates.japan.built",
        extra={
            "template_id": str(template.id),
            "slug": template.slug,
            "node_count": total_nodes,
            "edge_count": total_edges,
        },
    )
    return template


__all__ = [
    "JAPAN_TEMPLATE_NAME",
    "JAPAN_TEMPLATE_SLUG",
    "TRIP_ANCHOR",
    "build_japan_template",
]
