"""Day-by-day derivation of an itinerary for export rendering.

A SIMPLIFIED Python sibling of the web journal's ``toJournal.ts``: scheduled
root nodes group by their LOCAL calendar date (each node's own
``tz_offset_minutes``), attached notes hang on their host item, unscheduled
nodes form the Collection, and a multi-day card's subgraph children are laid
onto ``parent day + (index - 1)`` as journey beats. The journal's quiet
moment / gap / elision / alternative-group presentation logic is deliberately
NOT ported — an export spells out what is planned, not the ambience.

Everything here is pure data (frozen dataclasses) so the renderers and the
day-notes prompt builder can only ever see graph-derived content — that
signature is the redaction guarantee (no Dossier / OSINT / profile input).
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostKind, Itinerary, Node, NodeStatus, NodeType
from app.services.itineraries import _serialize_starts_at, _tz_offset_from_metadata
from app.services.node_cost import resolve_party_size, sum_node_costs


@dataclass(frozen=True)
class JourneyRef:
    """Membership of a derived journey beat: day ``index`` of ``total`` inside
    the multi-day card ``parent_title``."""

    parent_title: str
    index: int
    total: int


@dataclass(frozen=True)
class ExportItem:
    """One line of the export: a scheduled card, a Collection idea, or a beat."""

    node_id: str
    type: str
    title: str
    status: str
    start_local: datetime | None
    duration_minutes: int | None
    location: str | None
    cost_amount: Decimal | None
    cost_currency: str | None
    cost_kind: str | None
    altitude_m: int | None
    tz_offset_minutes: int | None
    notes: tuple[str, ...] = ()
    description: str | None = None
    journey: JourneyRef | None = None


@dataclass(frozen=True)
class ExportDay:
    """One local calendar day of the trip."""

    day_date: date
    label: str
    items: tuple[ExportItem, ...]
    night_hotel: str | None
    subtotals: dict[str, Decimal]
    tz_offset_minutes: int | None


@dataclass(frozen=True)
class ExportTrip:
    """The complete export view of one itinerary (trunk or fork)."""

    itinerary_id: str
    title: str
    brief: str | None
    timing_kind: str | None
    date_start: date | None
    date_end: date | None
    duration_nights: int | None
    timing_note: str | None
    is_fork: bool
    party_size: int
    days: tuple[ExportDay, ...] = ()
    collection: tuple[ExportItem, ...] = ()
    totals: dict[str, Decimal] = field(default_factory=dict)


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """Vendor descriptions arrive as HTML; exports render text only."""
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _location_label(metadata: Any) -> str | None:
    """The human-readable place label out of ``metadata.snapshot.location``."""
    if not isinstance(metadata, dict):
        return None
    snapshot = metadata.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    location = snapshot.get("location")
    if isinstance(location, str) and location:
        return location
    if isinstance(location, dict):
        label = location.get("label")
        if isinstance(label, str) and label:
            return label
    return None


def _description(metadata: Any) -> str | None:
    """A short plain-text description from the card snapshot, if any."""
    if not isinstance(metadata, dict):
        return None
    snapshot = metadata.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    for key in ("description", "description_html"):
        raw = snapshot.get(key)
        if isinstance(raw, str) and raw.strip():
            return _strip_html(raw)
    return None


def _subgraph_day_meta(metadata: Any) -> dict[str, Any]:
    """The materializer's per-day fields (``metadata.subgraph_day``)."""
    if isinstance(metadata, dict):
        raw = metadata.get("subgraph_day")
        if isinstance(raw, dict):
            return raw
    return {}


def _start_local(node: Node) -> tuple[datetime | None, int | None]:
    """(tz-aware local start, duration_minutes) via the graph read's serializer."""
    tz_offset = _tz_offset_from_metadata(node.metadata_)
    iso_start, duration = _serialize_starts_at(node.starts_at, tz_offset)
    if iso_start is None:
        return (None, duration)
    return (datetime.fromisoformat(iso_start), duration)


def _item_from_node(
    node: Node,
    *,
    attached_notes: dict[uuid.UUID, list[str]],
    journey: JourneyRef | None = None,
    start_local: datetime | None = None,
    duration_minutes: int | None = None,
) -> ExportItem:
    return ExportItem(
        node_id=str(node.id),
        type=node.type.value,
        title=node.title,
        status=node.status.value,
        start_local=start_local,
        duration_minutes=duration_minutes,
        location=_location_label(node.metadata_),
        cost_amount=node.cost_amount,
        cost_currency=node.cost_currency,
        cost_kind=node.cost_kind.value if node.cost_kind is not None else None,
        altitude_m=node.altitude_m,
        tz_offset_minutes=_tz_offset_from_metadata(node.metadata_),
        notes=tuple(attached_notes.get(node.id, ())),
        description=_description(node.metadata_),
        journey=journey,
    )


def _day_label(day: date, anchor: date | None) -> str:
    if anchor is None:
        return day.isoformat()
    return f"Day {(day - anchor).days + 1}"


def _modal_tz_offset(items: list[ExportItem]) -> int | None:
    offsets = [i.tz_offset_minutes for i in items if i.tz_offset_minutes is not None]
    if not offsets:
        return None
    return Counter(offsets).most_common(1)[0][0]


def _night_hotel(hotels: list[tuple[ExportItem, date, date | None]], day: date) -> str | None:
    """The hotel covering the night of ``day``: its stay starts on/before the
    day and either has no known end or checks out strictly after it. Ties go to
    the most recent check-in (a same-day hotel change means the new hotel)."""
    best: tuple[date, str] | None = None
    for item, start_day, end_day in hotels:
        if start_day > day:
            continue
        if end_day is not None and end_day <= day:
            continue
        if best is None or start_day >= best[0]:
            best = (start_day, item.title)
    return best[1] if best is not None else None


async def load_export_trip(session: AsyncSession, itinerary: Itinerary) -> ExportTrip:
    """Assemble the full export view for one itinerary (trunk or fork).

    Includes non-discarded, selected-branch, non-tombstoned nodes only —
    the same population the graph read renders and ``sum_node_costs`` prices.
    """
    rows = (
        (
            await session.execute(
                select(Node).where(
                    Node.itinerary_id == itinerary.id,
                    Node.status != NodeStatus.discarded,
                    Node.is_selected_alt.is_(True),
                    Node.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    party_size = await resolve_party_size(session, itinerary.id)
    totals = await sum_node_costs(session, itinerary.id)

    # Attached notes ride their host item; the note body is its title.
    attached_notes: dict[uuid.UUID, list[str]] = {}
    children_by_parent: dict[uuid.UUID, list[Node]] = {}
    roots: list[Node] = []
    for node in rows:
        if node.attached_to_node_id is not None and node.type is NodeType.note:
            attached_notes.setdefault(node.attached_to_node_id, []).append(node.title)
        elif node.parent_subgraph_id is not None:
            children_by_parent.setdefault(node.parent_subgraph_id, []).append(node)
        else:
            roots.append(node)
    for children in children_by_parent.values():
        children.sort(
            key=lambda c: (
                idx
                if isinstance(idx := _subgraph_day_meta(c.metadata_).get("index"), int)
                else 10**6
            )
        )

    scheduled: list[tuple[date, ExportItem]] = []
    collection: list[ExportItem] = []
    hotels: list[tuple[ExportItem, date, date | None]] = []
    for node in roots:
        start_local, duration = _start_local(node)
        if start_local is None:
            collection.append(_item_from_node(node, attached_notes=attached_notes))
            continue
        item = _item_from_node(
            node,
            attached_notes=attached_notes,
            start_local=start_local,
            duration_minutes=duration,
        )
        day = start_local.date()
        scheduled.append((day, item))
        if node.type is NodeType.hotel:
            end_day = (
                (start_local + timedelta(minutes=duration)).date() if duration is not None else None
            )
            hotels.append((item, day, end_day))

        # Journey beats: the card's internal day-by-day laid onto calendar days.
        children = children_by_parent.get(node.id, [])
        total = len(children)
        for i, child in enumerate(children):
            meta = _subgraph_day_meta(child.metadata_)
            raw_index = meta.get("index")
            index = raw_index if isinstance(raw_index, int) else i + 1
            hours = meta.get("hours")
            beat_minutes = round(hours * 60) if isinstance(hours, int | float) else None
            beat = _item_from_node(
                child,
                attached_notes=attached_notes,
                journey=JourneyRef(parent_title=node.title, index=index, total=total),
                duration_minutes=beat_minutes,
            )
            scheduled.append((day + timedelta(days=index - 1), beat))

    days_present = sorted({d for d, _ in scheduled})
    anchor = (
        itinerary.days_anchor or itinerary.date_start or (days_present[0] if days_present else None)
    )

    days: list[ExportDay] = []
    for day in days_present:
        items = [item for d, item in scheduled if d == day]
        # Timed items in start order; all-day beats and untimed items after.
        items.sort(
            key=lambda i: (
                (0, i.start_local.timetz().isoformat()) if i.start_local is not None else (1, "")
            )
        )
        subtotals: dict[str, Decimal] = {}
        for item in items:
            if item.cost_amount is None or item.cost_currency is None:
                continue
            amount = (
                item.cost_amount * max(party_size, 1)
                if item.cost_kind == CostKind.per_person.value
                else item.cost_amount
            )
            subtotals[item.cost_currency] = subtotals.get(item.cost_currency, Decimal(0)) + amount
        days.append(
            ExportDay(
                day_date=day,
                label=_day_label(day, anchor),
                items=tuple(items),
                night_hotel=_night_hotel(hotels, day),
                subtotals=subtotals,
                tz_offset_minutes=_modal_tz_offset(items),
            )
        )

    collection.sort(key=lambda i: i.title.lower())
    return ExportTrip(
        itinerary_id=str(itinerary.id),
        title=itinerary.title,
        brief=itinerary.brief,
        timing_kind=itinerary.timing_kind.value if itinerary.timing_kind is not None else None,
        date_start=itinerary.date_start,
        date_end=itinerary.date_end,
        duration_nights=itinerary.duration_nights,
        timing_note=itinerary.timing_note,
        is_fork=itinerary.forked_from_id is not None,
        party_size=party_size,
        days=tuple(days),
        collection=tuple(collection),
        totals=totals,
    )
