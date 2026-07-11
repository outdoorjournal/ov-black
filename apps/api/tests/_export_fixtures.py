"""Builders for export dataclass fixtures shared by the export test files."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.services.export.grouping import ExportDay, ExportItem, ExportTrip, JourneyRef


def make_item(
    *,
    type: str = "experience",
    title: str = "Tea ceremony",
    status: str = "pending",
    start: str | None = "2026-06-01T09:00:00+09:00",
    duration_minutes: int | None = 60,
    location: str | None = None,
    cost: str | None = None,
    currency: str | None = None,
    cost_kind: str | None = None,
    altitude_m: int | None = None,
    notes: tuple[str, ...] = (),
    description: str | None = None,
    journey: JourneyRef | None = None,
) -> ExportItem:
    start_local = datetime.fromisoformat(start) if start else None
    tz_offset: int | None = None
    if start_local is not None and start_local.utcoffset() is not None:
        offset = start_local.utcoffset()
        assert offset is not None
        tz_offset = int(offset.total_seconds() // 60)
    return ExportItem(
        node_id="00000000-0000-0000-0000-000000000000",
        type=type,
        title=title,
        status=status,
        start_local=start_local,
        duration_minutes=duration_minutes,
        location=location,
        cost_amount=Decimal(cost) if cost else None,
        cost_currency=currency,
        cost_kind=cost_kind,
        altitude_m=altitude_m,
        tz_offset_minutes=tz_offset,
        notes=notes,
        description=description,
        journey=journey,
    )


def make_day(
    day_date: date,
    items: tuple[ExportItem, ...],
    *,
    label: str | None = None,
    night_hotel: str | None = None,
    subtotals: dict[str, Decimal] | None = None,
) -> ExportDay:
    offsets = [i.tz_offset_minutes for i in items if i.tz_offset_minutes is not None]
    return ExportDay(
        day_date=day_date,
        label=label or f"Day {day_date.day}",
        items=items,
        night_hotel=night_hotel,
        subtotals=subtotals or {},
        tz_offset_minutes=offsets[0] if offsets else None,
    )


def make_trip(
    days: tuple[ExportDay, ...],
    *,
    title: str = "Kyoto in June",
    brief: str | None = "A quiet week of gardens and food",
    collection: tuple[ExportItem, ...] = (),
    totals: dict[str, Decimal] | None = None,
    party_size: int = 2,
    is_fork: bool = False,
) -> ExportTrip:
    return ExportTrip(
        itinerary_id="00000000-0000-0000-0000-0000000000ff",
        title=title,
        brief=brief,
        timing_kind="exact",
        date_start=days[0].day_date if days else None,
        date_end=days[-1].day_date if days else None,
        duration_nights=len(days) - 1 if days else None,
        timing_note=None,
        is_fork=is_fork,
        party_size=party_size,
        days=days,
        collection=collection,
        totals=totals or {},
    )
