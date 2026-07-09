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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.providers.duffel import summarize_offer
from app.inventory.registry import InventoryCtx, InventoryProviderRegistry
from app.inventory.schemas import InventoryItem
from app.models import (
    EdgeType,
    Itinerary,
    ItineraryStatus,
    ItineraryTimingKind,
    NodeStatus,
    NodeType,
)
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


# The whole curated spine is in Japan (Tokyo / Kyoto / Hiroshima), so every
# ``hhmm`` slot is Japan-local wall-clock. Tag placements with JST rather than
# the trip_start_at frame (UTC by default) so the timeline reads Tokyo time —
# a 19:30 dinner shows at 19:30, not 04:30. Flights override this with their
# own provider tz.
_JST = timezone(timedelta(hours=9))


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
    # Days to add to ``day`` when picking a flight's search departure_date. A
    # trans-Pacific eastbound red-eye departs the calendar day BEFORE it lands
    # in Tokyo, so the arrival flight searches ``day - 1`` to touch down on the
    # trip's first day rather than after the day-0 activities. 0 = depart on
    # the placement day (the westbound return arrives the same date it leaves).
    depart_day_offset: int = 0


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
        # Eastbound red-eye: depart LAX the day before to land on trip day 0.
        depart_day_offset=-1,
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


def _flight_schedule(metadata: dict[str, Any]) -> tuple[str | None, int | None]:
    """(starts_at, duration_minutes) for a flight from its card metadata.

    A flight is the one stop whose real timing the provider gives us: Duffel's
    ``depart_at`` / ``arrive_at`` (tz-aware after the offer is localized). We
    anchor the node's ``starts_at`` range on the true flight — lower bound =
    departure, width = arrival − departure — so the tile lands at the real time
    across zones instead of the curated placeholder slot, and its span matches
    the depart→arrive line the card renders. Returns ``(None, None)`` when an
    endpoint is missing or unparseable so the caller keeps the curated slot.
    """
    dep = metadata.get("depart_at")
    arr = metadata.get("arrive_at")
    if not isinstance(dep, str) or not dep:
        return (None, None)
    try:
        dep_dt = datetime.fromisoformat(dep)
    except ValueError:
        return (None, None)
    if not isinstance(arr, str) or not arr:
        return (dep, None)
    try:
        arr_dt = datetime.fromisoformat(arr)
        duration = round((arr_dt - dep_dt).total_seconds() / 60)
    except (ValueError, TypeError):
        # Unparseable arrival or a naive/aware mismatch — anchor at departure,
        # leave the width to the caller/timeline default rather than guess.
        return (dep, None)
    return (dep, duration if duration > 0 else None)


def _pick(items: list[InventoryItem], kind: str) -> InventoryItem | None:
    """First item matching the desired kind, else the first item at all."""
    for it in items:
        if it.kind == kind:
            return it
    return items[0] if items else None


def _pick_flight(items: list[InventoryItem], target_arrival: date) -> InventoryItem | None:
    """Earliest flight that ARRIVES on ``target_arrival`` (its local date).

    Duffel returns offers cheapest-first, but the cheapest LAX→HND is often a
    near-midnight red-eye — or a connection that lands at 23:30 — so even
    landing on the right day it arrives AFTER the day-0 evening plan. So among
    offers whose arrival lands on the intended day, take the EARLIEST arrival:
    a midday touchdown leaves room for the day's activities. Fall back to the
    plain cheapest flight when none land on the day (better a real flight than
    none).
    """
    flights = [it for it in items if it.kind == "flight"]
    on_day: list[tuple[datetime, InventoryItem]] = []
    for it in flights:
        arr = summarize_offer(it.raw).get("arrive_at")
        if not isinstance(arr, str):
            continue
        try:
            arr_dt = datetime.fromisoformat(arr)
        except ValueError:
            continue
        if arr_dt.date() == target_arrival:
            on_day.append((arr_dt, it))
    if on_day:
        on_day.sort(key=lambda pair: pair[0])
        return on_day[0][1]
    return flights[0] if flights else (items[0] if items else None)


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
        depart = (
            (trip_start_at + timedelta(days=stop.day + stop.depart_day_offset)).date().isoformat()
        )
        filters.update(
            origin=stop.origin,
            destination=stop.destination,
            departure_date=depart,
            cabin_class=stop.cabin_class or "business",
            adults=2,
            # Widen past the cheapest handful: the day-0 arrival pick needs
            # enough offers to find a midday touchdown (nonstops price higher
            # than the red-eye connections that dominate the cheapest few).
            limit=30,
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
    if stop.kind == "flight":
        # ``day`` is the intended arrival day; prefer an offer that lands then.
        target_arrival = (trip_start_at + timedelta(days=stop.day)).date()
        return _pick_flight(items, target_arrival)
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
    last_day_offset = 0

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
        # Take the trip's start DATE and place the slot at its Japan-local
        # wall-clock (strip the incoming UTC frame, re-tag JST) so days/times
        # read as Tokyo time on the timeline.
        placed = trip_start_at.replace(tzinfo=None) + timedelta(days=stop.day, hours=h, minutes=m)
        starts_at = placed.replace(tzinfo=_JST).isoformat()
        metadata = inventory_item_to_card_metadata(item)
        duration_minutes = stop.duration_minutes
        # Flights carry their own real schedule from Duffel; anchor on it so the
        # tile matches the card instead of the curated slot. Meals/experiences
        # (Google Places gives no canonical time) keep the curated placement.
        if stop.kind == "flight":
            flight_start, flight_duration = _flight_schedule(metadata)
            if flight_start is not None:
                starts_at = flight_start
                if flight_duration is not None:
                    duration_minutes = flight_duration
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
            duration_minutes=duration_minutes,
        )
        if isinstance(result, ItineraryError):
            skipped.append(f"{stop.label} (write {result.outcome.value})")
            continue

        ordered_ids.append(result.id)
        last_day_offset = max(last_day_offset, stop.day)
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

    # The seed schedules concrete calendar dates from ``trip_start_at``, so the
    # trip is born PINNED (Wave E): ``timing_kind=exact`` makes it bookable
    # (booking gates on pinned dates, ADV-17) and renders real dates instead of
    # Day-N ordinals. Overwrites the per-node anchor stamp, which — with no
    # declared dates on the fresh row — defaulted to today rather than Day 1.
    trip_start_date = trip_start_at.replace(tzinfo=None).date()
    itinerary.timing_kind = ItineraryTimingKind.exact
    itinerary.date_start = trip_start_date
    itinerary.date_end = trip_start_date + timedelta(days=last_day_offset)
    itinerary.days_anchor = trip_start_date

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
