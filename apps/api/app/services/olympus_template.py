"""Mt Olympus campaign spine builder — cornerstone-led, length-variant templates.

Composes each shipped spine (5 / 7 / 14 nights) from three parts rather than
slicing one hand-authored day-list (see :mod:`app.seed_data.olympus_itinerary`):

1. **Arrival** — a Litochoro base (a night-bar lane). No inbound flight: we
   don't know the traveler's origin, so flights are proposed in conversation.
2. **The cornerstone** — a single anchor card for the real OV adventure, carrying
   its cover/gallery/price enrichment AND its day-by-day itinerary as a SUBGRAPH.
   The subgraph children lay across the mountain days as the trip's experiences
   (the frontend's ``deriveJourneyBeats`` spreads them from the anchor's day
   forward). This is the ONLY mountain content — nothing hand-authored competes.
3. **The extension** — the grand tour AFTER the guided ascent, shifted past the
   cornerstone's day-span and prefix-sliced to fill the remaining nights.

So the cornerstone owns the mountain segment and the extension owns the days
after it — a beat and a hand-authored card never land on the same day. Each build
is idempotent via ``find_or_create_template`` + ``has_subgraph``.

The kickoff (``POST /itinerary/{id}/campaign/kickoff``) snaps the traveler's
chosen nights to one of these lengths and instantiates the matching template
onto their fork with :func:`app.services.templates.instantiate_into`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CardTemplate, EdgeType, NodeStatus, NodeType
from app.seed_data.japan_itinerary import FixtureItem
from app.seed_data.olympus_cornerstones import (
    BEAT_STOCK,
    OlympusCornerstone,
    cornerstone_for_nights,
)
from app.seed_data.olympus_itinerary import (
    ARRIVAL_ITEMS,
    EXTENSION_DAYS,
    TRIP_ANCHOR,
)
from app.services.subgraph import beat_subgraph_metadata, day_subgraph_metadata
from app.services.templates import (
    add_template_edge,
    add_template_node,
    find_or_create_template,
    has_subgraph,
)

logger = logging.getLogger("ov_black.templates.olympus")

_MINUTES_PER_DAY = 24 * 60
#: EEST (+03:00) — the fixture's zone; stamped so cards read in local time.
_EEST_OFFSET_MINUTES = 180

#: nights → template slug, mirrored by app.campaigns.registry OLYMPUS.
OLYMPUS_SPINE_SLUGS: dict[int, str] = {5: "olympus-5d", 7: "olympus-7d", 14: "olympus-14d"}


def _item_offset_minutes(item: FixtureItem) -> int:
    """Minutes from ``TRIP_ANCHOR`` to the item's authored start."""
    return int((item.starts_at - TRIP_ANCHOR).total_seconds() // 60)


def _node_type_for(item: FixtureItem) -> NodeType:
    return NodeType(item.attrs.kind)


def _is_night_bar(item: FixtureItem) -> bool:
    return bool(getattr(item.attrs, "night_bar", False))


def _item_metadata(item: FixtureItem) -> dict[str, Any]:
    metadata = item.attrs.model_dump(mode="json", exclude_none=True)
    utcoffset = item.starts_at.utcoffset()
    if utcoffset is not None:
        metadata["tz_offset_minutes"] = int(utcoffset.total_seconds() // 60)
    metadata["_seed_status"] = NodeStatus(item.status).value
    return metadata


async def _build_cornerstone_subgraph(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    parent_id: uuid.UUID,
    cornerstone: OlympusCornerstone,
) -> tuple[int, int]:
    """Add the cornerstone's day-by-day itinerary as ``parent_id``'s children.

    Mirrors :func:`app.services.subgraph.materialize_day_subgraph` in template
    space, chained by ``follows`` edges. A day that ships authored ``beats``
    lands one ``experience`` child PER BEAT (its own title, an ``hhmm`` clock
    time within the day, a duration, a description, and a hero image drawn
    from :data:`BEAT_STOCK` — repeats of a category rotate through its set so
    three dinners get three different shots); a beat-less day falls back to
    the single ``Day N — title`` child the inventory-born path produces.
    Returns ``(node_count, edge_count)`` added. No-op (0, 0) when the
    cornerstone ships no baked days.
    """
    node_count = 0
    edge_count = 0
    previous: uuid.UUID | None = None
    stock_used: dict[str, int] = {}

    def next_stock_image(category: str | None) -> str | None:
        if category is None:
            return None
        pool = BEAT_STOCK[category]
        index = stock_used.get(category, 0)
        stock_used[category] = index + 1
        return pool[index % len(pool)]

    async def add_child(title: str, metadata: dict[str, Any]) -> None:
        nonlocal node_count, edge_count, previous
        child = await add_template_node(
            session,
            template_id=template_id,
            type=NodeType.experience,
            title=title,
            parent_id=parent_id,
            metadata=metadata,
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

    for corner_day in cornerstone.days:
        day = corner_day.as_itinerary_day()
        if corner_day.beats:
            for beat in corner_day.beats:
                await add_child(
                    beat.title,
                    beat_subgraph_metadata(
                        day,
                        title=beat.title,
                        hhmm=beat.hhmm,
                        duration_minutes=beat.duration_minutes,
                        description=beat.description,
                        image=next_stock_image(beat.stock),
                    ),
                )
        else:
            await add_child(f"Day {day.day} — {day.title}", day_subgraph_metadata(day))
    return node_count, edge_count


async def build_olympus_template(session: AsyncSession, *, nights: int) -> CardTemplate:
    """Find-or-create the ``nights``-length Olympus spine.

    ``nights`` must be one of :data:`OLYMPUS_SPINE_SLUGS`. Composes arrival + the
    cornerstone anchor (with its day-by-day SUBGRAPH) + a shifted, prefix-sliced
    extension, so the guided ascent owns the mountain days and the grand tour owns
    the days after it.
    """
    slug = OLYMPUS_SPINE_SLUGS.get(nights)
    if slug is None:
        raise ValueError(f"unsupported Olympus spine length: {nights}")

    # Real OV trip this spine is built around — the longest spine anchors on the
    # full "Path to Symbolism" ascent, the shorter ones on the 2-day summit push.
    cornerstone = cornerstone_for_nights(nights, longest=max(OLYMPUS_SPINE_SLUGS))
    # The mountain segment is exactly as long as the cornerstone's own itinerary;
    # the extension picks up on the day after it and fills the remaining nights.
    span_days = len(cornerstone.days)
    extension_days = EXTENSION_DAYS[: max(0, nights - span_days)]

    template, created = await find_or_create_template(
        session,
        slug=slug,
        name=f"Mount Olympus · {nights} nights",
        description=(
            f"Curated {nights}-night Mt Olympus / Greece spine — a guided "
            f"{cornerstone.title} ascent, then the grand tour of the north."
        ),
        metadata={
            "trip_anchor_iso": TRIP_ANCHOR.isoformat(),
            "campaign_id": "olympus",
            "nights": nights,
            "cornerstone_span_days": span_days,
        },
    )
    if not created and await has_subgraph(session, template_id=template.id):
        logger.info(
            "templates.olympus.skip_rebuild",
            extra={"template_id": str(template.id), "slug": slug, "nights": nights},
        )
        return template

    total_nodes = 0
    total_edges = 0
    # A single ``follows`` chain threads the spine's scheduled cards in start
    # order; night-bar lodging sits in its own lane and stays off the chain.
    prev_spine: uuid.UUID | None = None

    async def add_node_from(
        *,
        type_: NodeType,
        title: str,
        offset_minutes: int,
        duration_minutes: int,
        metadata: dict[str, Any],
        on_chain: bool,
    ) -> uuid.UUID:
        nonlocal total_nodes, total_edges, prev_spine
        tnode = await add_template_node(
            session,
            template_id=template.id,
            type=type_,
            title=title,
            starts_at_offset_minutes=offset_minutes,
            duration_minutes=duration_minutes,
            metadata=metadata,
        )
        total_nodes += 1
        if on_chain:
            if prev_spine is not None:
                await add_template_edge(
                    session,
                    template_id=template.id,
                    from_template_node_id=prev_spine,
                    to_template_node_id=tnode.id,
                    type=EdgeType.follows,
                )
                total_edges += 1
            prev_spine = tnode.id
        return tnode.id

    # 1. Arrival — the Litochoro base (a night-bar, off-chain). No flight is
    # seeded; the traveler's origin is unknown until they tell us.
    for item in ARRIVAL_ITEMS:
        await add_node_from(
            type_=_node_type_for(item),
            title=item.title,
            offset_minutes=_item_offset_minutes(item),
            duration_minutes=item.duration_minutes,
            metadata=_item_metadata(item),
            on_chain=not _is_night_bar(item),
        )

    # 2. The cornerstone anchor — one experience card that IS the guided OV trip:
    # its cover/gallery/price enrich it, and its day-by-day itinerary hangs off it
    # as a subgraph whose beats lay across the mountain days at their authored
    # clock times (the anchor's own start comes from the cornerstone — the full
    # ascent begins with a mid-afternoon pickup, the 2-day push meets at 10:00).
    hh, mm = (int(part) for part in cornerstone.anchor_hhmm.split(":", 1))
    anchor_metadata: dict[str, Any] = {
        "category": "mountaineering",
        "difficulty": "strenuous",
        "energy_required": 5,
        "location": {"lat": 40.0885, "lng": 22.3489, "label": "Mount Olympus"},
        "tz_offset_minutes": _EEST_OFFSET_MINUTES,
        "_seed_status": NodeStatus.pending.value,
        **cornerstone.enrichment(),
    }
    anchor_id = await add_node_from(
        type_=NodeType.experience,
        title=cornerstone.title,
        offset_minutes=hh * 60 + mm,
        duration_minutes=span_days * _MINUTES_PER_DAY,
        metadata=anchor_metadata,
        on_chain=True,
    )
    n, e = await _build_cornerstone_subgraph(
        session, template_id=template.id, parent_id=anchor_id, cornerstone=cornerstone
    )
    total_nodes += n
    total_edges += e

    # 3. Extension — shifted past the cornerstone's span, then prefix-sliced. Its
    # items are authored from their own day 0, so add span_days to every offset.
    shift = span_days * _MINUTES_PER_DAY
    for day in extension_days:
        for item in day.items:
            await add_node_from(
                type_=_node_type_for(item),
                title=item.title,
                offset_minutes=_item_offset_minutes(item) + shift,
                duration_minutes=item.duration_minutes,
                metadata=_item_metadata(item),
                on_chain=not _is_night_bar(item),
            )

    await session.commit()
    logger.info(
        "templates.olympus.built",
        extra={
            "template_id": str(template.id),
            "slug": slug,
            "nights": nights,
            "cornerstone_span_days": span_days,
            "node_count": total_nodes,
            "edge_count": total_edges,
        },
    )
    return template


__all__ = ["OLYMPUS_SPINE_SLUGS", "build_olympus_template"]
