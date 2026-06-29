"""Build a Japan itinerary from LIVE inventory (Duffel + Google Places).

The counterpart to ``japan_template.py`` (a hand-authored *static* seed). This
assembles a real, visualizable itinerary by querying the enabled inventory
providers at call time: Duffel for the long-haul flights, Google Places for
meals and experiences across Tokyo / Kyoto / Hiroshima. The trip STRUCTURE
(which days, what kind of stop, the search query + city) is curated here; the
CONTENT each card shows — restaurant names, addresses, price level, photos,
flight carriers + times — is whatever the providers return now. Results are
cached (see ``inventory_cache``) so repeat builds are fast and survive a
provider hiccup.

Coverage is honest: flights (Duffel) + meals/experiences (Google Places) are
the kinds we hold live keys for. Hotels (Ratehawk) and rail/transit have no
live provider configured locally, so they're simply absent — better an empty
slot than a fake one.

Resilient by design: a query that returns nothing, a provider error, or a
write rejection skips that stop and records it in the report — never aborts
the build.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.registry import InventoryCtx, InventoryProviderRegistry
from app.inventory.schemas import InventoryItem
from app.models import EdgeType, Itinerary, ItineraryStatus, NodeStatus, NodeType
from app.services.card_mapping import inventory_item_to_card_metadata
from app.services.inventory_cache import cached_search
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    add_edge,
    add_node,
)
from app.services.node_cost import cost_from_inventory_item

logger = logging.getLogger("ov_black.demos.japan_live")


@dataclass(frozen=True)
class _Stop:
    """One curated slot in the trip. The provider query is fixed; the result
    is live. ``label`` names the slot for the build report.
    """

    label: str
    day: int  # 0-based offset from trip start
    hhmm: str
    duration_minutes: int
    status: str
    kind: str  # "flight" | "meal" | "experience"
    source: str  # "duffel" | "google_places"
    keyword: str | None = None
    near: tuple[float, float] | None = None  # (lat, lng) location bias for Places
    radius_m: int = 4000
    # Flight-only
    origin: str | None = None
    destination: str | None = None
    cabin_class: str | None = None


# City anchors for Google Places location bias.
_GINZA = (35.6717, 139.7650)
_ASAKUSA = (35.7148, 139.7967)
_TSUKIJI = (35.6654, 139.7707)
_SHINJUKU = (35.6896, 139.7006)
_GION = (35.0037, 135.7752)
_ARASHIYAMA = (35.0170, 135.6717)
_FUSHIMI = (34.9671, 135.7727)
_HIROSHIMA = (34.3853, 132.4553)
_MIYAJIMA = (34.2960, 132.3199)


# The curated 5-day spine. Times are local placement on the timeline; the
# cards render the providers' own times/prices.
_PLAN: list[_Stop] = [
    # ── Day 1 · Tokyo arrival ──
    _Stop(
        "Arrival flight LAX→HND",
        0,
        "16:10",
        660,
        "confirmed",
        "flight",
        "duffel",
        origin="LAX",
        destination="HND",
        cabin_class="business",
    ),
    _Stop(
        "Sushi dinner · Ginza",
        0,
        "19:30",
        120,
        "booked",
        "meal",
        "google_places",
        keyword="sushi omakase",
        near=_GINZA,
    ),
    _Stop(
        "Sensō-ji & Asakusa",
        0,
        "21:30",
        60,
        "approved",
        "experience",
        "google_places",
        keyword="Sensō-ji temple",
        near=_ASAKUSA,
    ),
    # ── Day 2 · Tokyo ──
    _Stop(
        "Tsukiji Outer Market",
        1,
        "09:00",
        120,
        "approved",
        "experience",
        "google_places",
        keyword="Tsukiji Outer Market",
        near=_TSUKIJI,
    ),
    _Stop(
        "Ramen lunch · Shinjuku",
        1,
        "12:30",
        75,
        "booked",
        "meal",
        "google_places",
        keyword="ramen",
        near=_SHINJUKU,
    ),
    _Stop(
        "teamLab / Shinjuku Gyoen",
        1,
        "15:00",
        120,
        "proposed",
        "experience",
        "google_places",
        keyword="Shinjuku Gyoen National Garden",
        near=_SHINJUKU,
    ),
    # ── Day 3 · Kyoto ──
    _Stop(
        "Fushimi Inari Taisha",
        2,
        "09:00",
        120,
        "approved",
        "experience",
        "google_places",
        keyword="Fushimi Inari Taisha",
        near=_FUSHIMI,
    ),
    _Stop(
        "Arashiyama Bamboo Grove",
        2,
        "12:30",
        90,
        "approved",
        "experience",
        "google_places",
        keyword="Arashiyama Bamboo Grove",
        near=_ARASHIYAMA,
    ),
    _Stop(
        "Kaiseki dinner · Gion",
        2,
        "19:00",
        120,
        "booked",
        "meal",
        "google_places",
        keyword="kaiseki",
        near=_GION,
    ),
    # ── Day 4 · Hiroshima & Miyajima ──
    _Stop(
        "Itsukushima Shrine",
        3,
        "11:00",
        120,
        "approved",
        "experience",
        "google_places",
        keyword="Itsukushima Shrine",
        near=_MIYAJIMA,
    ),
    _Stop(
        "Okonomiyaki lunch · Hiroshima",
        3,
        "14:00",
        75,
        "booked",
        "meal",
        "google_places",
        keyword="okonomiyaki",
        near=_HIROSHIMA,
    ),
    # ── Day 5 · departure ──
    _Stop(
        "Return flight HND→LAX",
        4,
        "15:25",
        600,
        "confirmed",
        "flight",
        "duffel",
        origin="HND",
        destination="LAX",
        cabin_class="business",
    ),
]


@dataclass
class LiveBuildReport:
    itinerary_id: uuid.UUID
    node_count: int
    edge_count: int
    sourced: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":", 1)
    return int(h), int(m)


def _pick(items: list[InventoryItem], kind: str) -> InventoryItem | None:
    """First item matching the desired kind, else the first item at all."""
    for it in items:
        if it.kind == kind:
            return it
    return items[0] if items else None


async def _search_stop(
    registry: InventoryProviderRegistry,
    stop: _Stop,
    *,
    trip_start_at: datetime,
    ctx: InventoryCtx,
) -> InventoryItem | None:
    filters: dict[str, Any] = {"limit": 6}
    keyword = stop.keyword
    if stop.source == "duffel":
        depart = (trip_start_at + timedelta(days=stop.day)).date().isoformat()
        filters.update(
            origin=stop.origin,
            destination=stop.destination,
            departure_date=depart,
            cabin_class=stop.cabin_class or "business",
            adults=2,
        )
    elif stop.near is not None:
        filters.update(near_lat=stop.near[0], near_lng=stop.near[1], radius_m=stop.radius_m)

    try:
        items = await cached_search(
            registry,
            source=stop.source,
            kinds=[stop.kind],
            keyword=keyword,
            filters=filters,
            ctx=ctx,
        )
    except Exception as exc:  # noqa: BLE001 — a dead provider skips one stop, not the trip
        logger.warning(
            "japan_live.search_failed",
            extra={"label": stop.label, "source": stop.source, "error": str(exc)},
        )
        return None
    return _pick(items, stop.kind)


async def build_live_japan_itinerary(
    session: AsyncSession,
    registry: InventoryProviderRegistry,
    *,
    client_id: uuid.UUID,
    trip_start_at: datetime,
    created_by: uuid.UUID,
    title: str | None = None,
) -> LiveBuildReport:
    """Create a fresh itinerary and fill it from live provider results.

    Every node carries real provider metadata (``source`` / ``source_id`` +
    mapped card attrs) and a curated ``starts_at`` so the timeline lays it out.
    Stops are chained with ``follows`` edges in chronological order.
    """
    itinerary = Itinerary(
        title=title or "Japan · live concierge build",
        client_id=client_id,
        created_by=created_by,
        status=ItineraryStatus.draft,
    )
    session.add(itinerary)
    await session.flush()

    # Advisor actor bypasses the editor lock (services.itineraries._check_lock)
    # so the seed writes land directly on the fresh itinerary.
    actor = ActorContext(user_id=created_by, kind=ActorKind.ADVISOR, actor_id=str(created_by))
    ctx = InventoryCtx(actor_kind="user", actor_id=str(created_by))

    sourced: list[str] = []
    skipped: list[str] = []
    ordered_ids: list[uuid.UUID] = []

    for stop in _PLAN:
        item = await _search_stop(registry, stop, trip_start_at=trip_start_at, ctx=ctx)
        if item is None:
            skipped.append(f"{stop.label} (no result)")
            continue

        try:
            node_type = NodeType(item.kind)
        except ValueError:
            skipped.append(f"{stop.label} (unmappable kind {item.kind!r})")
            continue

        h, m = _hhmm(stop.hhmm)
        starts_at = (trip_start_at + timedelta(days=stop.day, hours=h, minutes=m)).isoformat()
        metadata = inventory_item_to_card_metadata(item)
        cost = cost_from_inventory_item(item)

        result = await add_node(
            session,
            actor,
            itinerary_id=itinerary.id,
            type=node_type,
            status=NodeStatus(stop.status),
            title=item.title,
            source=item.source,
            source_id=item.source_id,
            metadata=metadata,
            cost_amount=cost.amount if cost else None,
            cost_currency=cost.currency if cost else None,
            cost_kind=cost.kind if cost else None,
            starts_at=starts_at,
            duration_minutes=stop.duration_minutes,
        )
        if isinstance(result, ItineraryError):
            skipped.append(f"{stop.label} (write {result.outcome.value})")
            continue

        ordered_ids.append(result.id)
        sourced.append(f"{stop.label} → {item.title} [{item.source}]")

    # Chain the placed nodes chronologically (the plan is already in order).
    edge_count = 0
    for prev, cur in zip(ordered_ids, ordered_ids[1:], strict=False):
        edge_result = await add_edge(
            session,
            actor,
            itinerary_id=itinerary.id,
            from_node_id=prev,
            to_node_id=cur,
            type=EdgeType.follows,
        )
        if not isinstance(edge_result, ItineraryError):
            edge_count += 1

    await session.commit()
    await session.refresh(itinerary)

    logger.info(
        "demos.japan_live.built",
        extra={
            "itinerary_id": str(itinerary.id),
            "client_id": str(client_id),
            "sourced": len(sourced),
            "skipped": len(skipped),
            "edges": edge_count,
        },
    )
    return LiveBuildReport(
        itinerary_id=itinerary.id,
        node_count=len(ordered_ids),
        edge_count=edge_count,
        sourced=sourced,
        skipped=skipped,
    )


__all__ = ["LiveBuildReport", "build_live_japan_itinerary"]
