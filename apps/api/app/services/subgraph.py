"""Materialize an inventory item's internal journey as an embedded subgraph.

PRD "Subgraphs for self-contained experiences": a packaged multi-day trip
(an OV adventure) is one card on the itinerary, but inside it there's a
day-by-day journey with its own geo points. This service turns those days
into child nodes (``parent_subgraph_id`` = the experience node) chained by
``follows`` edges, so every surface reads the journey out of the graph
rather than re-parsing vendor payloads.

Deliberately generic over ``ItineraryDay`` rather than anything
OV-specific: advisor-authored reusable subgraph templates (future) can
feed the same shape through the same write path. Subgraph children are
derived content — they carry no ``source``/``source_id`` provenance of
their own (the parent owns it) and no schedule (the parent owns the time
slot; ``day_index`` + ``follows`` edges give the internal order).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.schemas import ItineraryDay
from app.models.itinerary import EdgeType, Node, NodeStatus, NodeType
from app.services.itineraries import ActorContext, ItineraryError, add_edge, add_node

logger = logging.getLogger("ov_black.services.subgraph")


def day_subgraph_metadata(day: ItineraryDay) -> dict[str, Any]:
    """Node ``metadata`` for one day: a renderable snapshot + typed extras.

    ``snapshot`` follows the legacy card shape so existing snapshot-reading
    cards render the child like any other node; ``subgraph_day`` carries the
    structured fields (1-based index, active hours, geo point, vendor HTML
    description) the expanded sub-journey view reads directly.

    Public so non-inventory subgraph builders (e.g. the Olympus campaign
    template's baked cornerstone days) emit byte-identical child metadata and
    render through the same journey view.
    """
    snapshot: dict[str, Any] = {"title": day.title}
    if day.location is not None and day.location.label:
        snapshot["location"] = day.location.label
    subgraph_day: dict[str, Any] = {"index": day.day}
    if day.hours is not None:
        subgraph_day["hours"] = day.hours
    if day.location is not None:
        if day.location.lat is not None:
            subgraph_day["lat"] = day.location.lat
        if day.location.lng is not None:
            subgraph_day["lng"] = day.location.lng
    if day.description:
        subgraph_day["description_html"] = day.description
    return {"snapshot": snapshot, "subgraph_day": subgraph_day}


def beat_subgraph_metadata(
    day: ItineraryDay,
    *,
    title: str,
    hhmm: str,
    duration_minutes: int | None = None,
    description: str | None = None,
    image: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    location_label: str | None = None,
) -> dict[str, Any]:
    """Node ``metadata`` for one BEAT — an inferred sub-moment within a day.

    Same envelope as :func:`day_subgraph_metadata` (a ``snapshot`` + a
    ``subgraph_day``), so beat children ride the existing journey-beat read
    path unchanged. The extras: ``hhmm`` places the beat at a local clock time
    within its day (instead of the generic morning start), ``duration_minutes``
    sizes it, ``description`` lands as the card's own description (top-level,
    the card-attrs socket every card view reads), and ``image`` gives the beat
    its own hero (``ambient_image`` + ``snapshot.cover_image`` — without one
    the journey view falls back to the parent's gallery rotation). ``index``
    still comes from the day the beat belongs to. Geo defaults to the day's,
    but a beat that happens elsewhere in the day (``lat``/``lng``/
    ``location_label``) overrides it so the card pins — and its Maps button
    lands — at the beat's own spot.
    """
    metadata = day_subgraph_metadata(day)
    metadata["snapshot"]["title"] = title
    subgraph_day = metadata["subgraph_day"]
    subgraph_day["hhmm"] = hhmm
    if lat is not None:
        subgraph_day["lat"] = lat
    if lng is not None:
        subgraph_day["lng"] = lng
    if location_label:
        subgraph_day["location_label"] = location_label
        metadata["snapshot"]["location"] = location_label
    # A beat with its own coordinates gets a top-level ``location`` object so the
    # detail view's "Open in Google Maps" / directions button pins at the beat's
    # spot (the button reads ``metadata.location`` — subgraph children otherwise
    # have none). Skipped for beats that inherit the day's geo, matching today.
    if lat is not None and lng is not None:
        location: dict[str, Any] = {"lat": lat, "lng": lng}
        if location_label:
            location["label"] = location_label
        metadata["location"] = location
    if duration_minutes is not None:
        subgraph_day["duration_minutes"] = duration_minutes
    if description:
        metadata["description"] = description
        subgraph_day["description_html"] = description
    elif "description_html" in subgraph_day:
        # A beat tells its own moment; never inherit the whole day's prose.
        del subgraph_day["description_html"]
    if image:
        metadata["ambient_image"] = image
        metadata["snapshot"]["cover_image"] = image
    return metadata


async def materialize_day_subgraph(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    parent_node_id: uuid.UUID,
    days: list[ItineraryDay],
    status: NodeStatus,
) -> list[Node]:
    """Create one child node per day under ``parent_node_id`` + follows edges.

    Children go through the normal ``add_node``/``add_edge`` write path so
    lock/queue + history invariants hold. Returns the created children in
    day order. A failure on one day raises after logging — the caller's
    parent node stays; a user delete of the parent cascades over whatever
    was materialized.
    """
    created: list[Node] = []
    previous: Node | None = None
    for day in days:
        result = await add_node(
            session,
            actor,
            itinerary_id=itinerary_id,
            type=NodeType.experience,
            status=status,
            title=f"Day {day.day} — {day.title}",
            parent_subgraph_id=parent_node_id,
            metadata=day_subgraph_metadata(day),
        )
        if isinstance(result, ItineraryError):
            logger.warning(
                "subgraph.materialize.day_failed",
                extra={
                    "itinerary_id": str(itinerary_id),
                    "parent_node_id": str(parent_node_id),
                    "day": day.day,
                    "outcome": result.outcome.value,
                },
            )
            raise SubgraphMaterializeError(result)
        if previous is not None:
            edge = await add_edge(
                session,
                actor,
                itinerary_id=itinerary_id,
                from_node_id=previous.id,
                to_node_id=result.id,
                type=EdgeType.follows,
                metadata={"reason": "day_sequence"},
            )
            if isinstance(edge, ItineraryError):
                logger.warning(
                    "subgraph.materialize.edge_failed",
                    extra={
                        "itinerary_id": str(itinerary_id),
                        "parent_node_id": str(parent_node_id),
                        "day": day.day,
                        "outcome": edge.outcome.value,
                    },
                )
                raise SubgraphMaterializeError(edge)
        created.append(result)
        previous = result
    logger.info(
        "subgraph.materialize",
        extra={
            "itinerary_id": str(itinerary_id),
            "parent_node_id": str(parent_node_id),
            "day_count": len(created),
        },
    )
    return created


class SubgraphMaterializeError(Exception):
    """A child node/edge write failed; wraps the service ItineraryError."""

    def __init__(self, error: ItineraryError) -> None:
        super().__init__(error.outcome.value)
        self.error = error
