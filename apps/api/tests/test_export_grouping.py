"""Export grouping: local-date day derivation, Collection, beats, night hotel."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from app.models import Itinerary
from app.services.export.grouping import (
    _day_label,
    _location_label,
    _night_hotel,
    _strip_html,
    load_export_trip,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._export_fixtures import make_item
from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── Pure units ──────────────────────────────────────────────────────────────


def test_strip_html() -> None:
    assert _strip_html("<p>Wander the <b>bamboo</b>&nbsp;grove &amp; eat</p>") == (
        "Wander the bamboo grove & eat"
    )


def test_location_label_accepts_string_and_dict() -> None:
    assert _location_label({"snapshot": {"location": "Lake Como, Italy"}}) == "Lake Como, Italy"
    assert _location_label({"snapshot": {"location": {"label": "Kyoto"}}}) == "Kyoto"
    assert _location_label({"snapshot": {"location": {"lat": 1}}}) is None
    assert _location_label({}) is None
    assert _location_label(None) is None


def test_day_label_uses_anchor() -> None:
    assert _day_label(date(2026, 6, 3), date(2026, 6, 1)) == "Day 3"
    assert _day_label(date(2026, 6, 1), None) == "2026-06-01"


def test_night_hotel_prefers_latest_checkin_and_handles_unbounded() -> None:
    ritz = make_item(type="hotel", title="The Ritz", start="2026-06-01T15:00:00+09:00")
    aman = make_item(type="hotel", title="Aman Kyoto", start="2026-06-03T15:00:00+09:00")
    hotels = [
        (ritz, date(2026, 6, 1), date(2026, 6, 3)),  # checks out morning of the 3rd
        (aman, date(2026, 6, 3), None),  # unbounded stay
    ]
    assert _night_hotel(hotels, date(2026, 6, 1)) == "The Ritz"
    assert _night_hotel(hotels, date(2026, 6, 2)) == "The Ritz"
    # Checkout day: the new hotel owns the night.
    assert _night_hotel(hotels, date(2026, 6, 3)) == "Aman Kyoto"
    # Unbounded stay keeps covering.
    assert _night_hotel(hotels, date(2026, 6, 5)) == "Aman Kyoto"
    assert _night_hotel(hotels, date(2026, 5, 31)) is None


# ── Integration: the full load path ─────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(itinerary_id: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.itineraries where id = :id"), {"id": itinerary_id}
            )
    finally:
        await engine.dispose()


async def _insert_node_full(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    type: str,
    title: str,
    status: str = "pending",
    starts_lower: datetime | None = None,
    starts_upper: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    parent_subgraph_id: uuid.UUID | None = None,
    attached_to_node_id: uuid.UUID | None = None,
    cost_amount: str | None = None,
    cost_currency: str | None = None,
    cost_kind: str | None = None,
    is_selected_alt: bool = True,
) -> uuid.UUID:
    """Raw insert covering the columns the export reads (metadata, subgraph,
    attachment, cost kind) that ``_graph_seed.insert_node`` doesn't take."""
    import json

    nid = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into public.nodes
              (id, itinerary_id, type, title, status, is_selected_alt, metadata,
               parent_subgraph_id, attached_to_node_id, starts_at,
               cost_amount, cost_currency, cost_kind)
            values (
              :id, :iid, cast(:type as public.node_type), :title,
              cast(:status as public.node_status), :sel, cast(:meta as jsonb),
              :psg, :att,
              case when cast(:lo as timestamptz) is null
                        and cast(:hi as timestamptz) is null then null
                   else tstzrange(cast(:lo as timestamptz), cast(:hi as timestamptz), '[)') end,
              cast(:ca as numeric), :cc, cast(:ck as public.cost_kind)
            )
            """
        ),
        {
            "id": nid,
            "iid": itinerary_id,
            "type": type,
            "title": title,
            "status": status,
            "sel": is_selected_alt,
            "meta": json.dumps(metadata or {}),
            "psg": parent_subgraph_id,
            "att": attached_to_node_id,
            "lo": starts_lower,
            "hi": starts_upper,
            "ca": cost_amount,
            "cc": cost_currency,
            "ck": cost_kind,
        },
    )
    await session.commit()
    return nid


async def _seed_party(session: AsyncSession, itinerary_id: uuid.UUID, size: int) -> None:
    party_id = uuid.uuid4()
    await session.execute(
        text("insert into public.parties (id, itinerary_id, label) values (:p, :i, 'all')"),
        {"p": party_id, "i": itinerary_id},
    )
    for n in range(size):
        await session.execute(
            text("insert into public.travelers (party_id, name) values (:p, :n)"),
            {"p": party_id, "n": f"t{n}"},
        )
    await session.commit()


def _utc(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


@integration
async def test_load_export_trip_full_scenario(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="Export scenario")
    try:
        await _seed_party(db_session, iid, 3)
        tokyo = {"tz_offset_minutes": 540}
        la = {"tz_offset_minutes": -420}

        # Day 1 (June 1 local Tokyo): morning temple, priced total.
        temple = await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="Fushimi Inari at dawn",
            starts_lower=_utc(2026, 6, 1, 0, 0),  # 09:00 +09:00
            starts_upper=_utc(2026, 6, 1, 2, 0),
            metadata={**tokyo, "snapshot": {"location": "Kyoto, Japan"}},
            cost_amount="100.00",
            cost_currency="USD",
            cost_kind="total",
        )
        # Attached note rides the temple.
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="note",
            title="Bring the good camera",
            attached_to_node_id=temple,
        )
        # An LA-zone node whose UTC instant is June 2 but LOCAL date is June 1
        # (21:30 -07:00) — groups onto Day 1, priced per person (party of 3).
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="meal",
            title="Send-off dinner",
            starts_lower=_utc(2026, 6, 2, 4, 30),
            starts_upper=_utc(2026, 6, 2, 6, 0),
            metadata=la,
            cost_amount="50.00",
            cost_currency="USD",
            cost_kind="per_person",
        )
        # Hotel: check-in June 1 15:00 local, checkout June 3 morning.
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="hotel",
            title="Hotel Okura",
            starts_lower=_utc(2026, 6, 1, 6, 0),
            starts_upper=_utc(2026, 6, 3, 1, 0),
            metadata=tokyo,
            cost_amount="300.00",
            cost_currency="USD",
            cost_kind="total",
        )
        # Day 3: a multi-day adventure whose 2 subgraph children become beats
        # on June 3 and June 4.
        adventure = await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="Kumano Kodo trek",
            starts_lower=_utc(2026, 6, 3, 0, 0),
            starts_upper=_utc(2026, 6, 3, 8, 0),
            metadata=tokyo,
        )
        for index, leg in ((1, "Ridge walk"), (2, "Hot spring descent")):
            await _insert_node_full(
                db_session,
                itinerary_id=iid,
                type="experience",
                title=leg,
                parent_subgraph_id=adventure,
                metadata={"subgraph_day": {"index": index, "hours": 6}},
            )
        # Unscheduled → Collection; discarded + deselected → invisible.
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="Maybe: tea auction",
            cost_amount="200.00",
            cost_currency="USD",
            cost_kind="total",
        )
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="Discarded idea",
            status="discarded",
        )
        await _insert_node_full(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="Losing alternative",
            is_selected_alt=False,
        )

        itinerary = await db_session.get(Itinerary, iid)
        assert itinerary is not None
        trip = await load_export_trip(db_session, itinerary)

        # Days: June 1 (grouped across zones), June 3, June 4 (beat only).
        assert [d.day_date for d in trip.days] == [
            date(2026, 6, 1),
            date(2026, 6, 3),
            date(2026, 6, 4),
        ]
        assert [d.label for d in trip.days] == ["Day 1", "Day 3", "Day 4"]

        day1 = trip.days[0]
        titles1 = [i.title for i in day1.items]
        assert titles1 == ["Fushimi Inari at dawn", "Hotel Okura", "Send-off dinner"]
        temple_item = day1.items[0]
        assert temple_item.notes == ("Bring the good camera",)
        assert temple_item.location == "Kyoto, Japan"
        assert temple_item.start_local is not None
        assert temple_item.start_local.strftime("%H:%M") == "09:00"
        # party_size = 3 companions + 1 account holder = 4 (resolve_party_size).
        # 100 (temple, total) + 300 (hotel, total) + 50×4 (dinner, per_person) = 600
        assert day1.subtotals == {"USD": Decimal("600.00")}
        assert day1.night_hotel == "Hotel Okura"

        day3 = trip.days[1]
        assert day3.night_hotel is None  # checkout morning of the 3rd
        beat_titles = [i.title for i in day3.items]
        assert beat_titles == ["Kumano Kodo trek", "Ridge walk"]
        beat = day3.items[1]
        assert beat.journey is not None
        assert (beat.journey.index, beat.journey.total) == (1, 2)
        assert beat.journey.parent_title == "Kumano Kodo trek"

        day4 = trip.days[2]
        assert [i.title for i in day4.items] == ["Hot spring descent"]

        # Collection holds only the unscheduled, live, selected idea.
        assert [i.title for i in trip.collection] == ["Maybe: tea auction"]
        # Totals: day items (600) + Collection tea auction (200, total) = 800.
        assert trip.totals == {"USD": Decimal("800.00")}
        assert trip.party_size == 4
        assert trip.is_fork is False
    finally:
        await _cleanup(iid)


@pytest.mark.parametrize("bad", [None, 42, [], {"lat": 1}])
def test_location_label_defensive(bad: Any) -> None:
    # A non-string, non-labelled location yields None (a plain string is valid).
    assert _location_label({"snapshot": {"location": bad}}) is None
