"""Standard Analyze runner — drive-time feasibility (B5 acceptance).

The headline B5 acceptance: a standard analyze over an itinerary with an
impossible drive-time gap yields a ``warn`` ``location_flux`` finding carrying
structured evidence. Also covers the feasible case (no finding, drive_times
still recorded) and that flight legs are skipped (schedule, not haversine).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest_asyncio
from app.models import FindingSeverity
from app.services.analyze_runners import standard
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import (
    LOCAL_DB_URL,
    insert_itinerary,
    insert_node,
    integration,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Real geography so haversine is exercised on production-shaped coordinates.
_TOKYO = (35.6812, 139.7671)
_OSAKA = (34.6937, 135.5023)  # ~400 km from Tokyo


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2024, 6, 20, h, m, tzinfo=UTC)


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


@integration
async def test_impossible_drive_emits_location_flux_warn(
    db_session: AsyncSession,
) -> None:
    iid = await insert_itinerary(db_session)
    a = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Tokyo museum",
        starts_lower=_at(9),
        starts_upper=_at(10),
        lat=_TOKYO[0],
        lng=_TOKYO[1],
    )
    b = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Osaka castle",
        starts_lower=_at(10, 10),
        starts_upper=_at(11),
        lat=_OSAKA[0],
        lng=_OSAKA[1],
    )
    output = await standard.run(db_session, itinerary_id=iid)

    flux = [f for f in output.findings if f.category == "location_flux"]
    assert len(flux) == 1
    f = flux[0]
    assert f.severity is FindingSeverity.warn
    assert f.node_id == b
    ev = f.evidence
    assert ev["from_node_id"] == str(a)
    assert ev["to_node_id"] == str(b)
    assert ev["available_min"] == 10
    assert ev["distance_km"] > 300  # Tokyo->Osaka is ~400 km
    assert ev["required_min"] > ev["available_min"]
    assert ev["mode"] == "drive"
    assert ev["max_speed_kmh"] > 0

    # The computed leg is also surfaced for Fill to reuse.
    assert f"{a}:{b}" in output.result_extra["drive_times"]


@integration
async def test_feasible_walk_emits_no_flux(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    # Two points ~0.5 km apart with a generous hour gap — easily walkable.
    a = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        starts_lower=_at(9),
        starts_upper=_at(10),
        lat=35.6812,
        lng=139.7671,
    )
    b = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        starts_lower=_at(11),
        starts_upper=_at(12),
        lat=35.6855,
        lng=139.7671,
    )
    output = await standard.run(db_session, itinerary_id=iid)
    assert [f for f in output.findings if f.category == "location_flux"] == []
    # drive_times still recorded for the pair.
    assert f"{a}:{b}" in output.result_extra["drive_times"]


@integration
async def test_flight_leg_skipped(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session)
    a = await insert_node(
        db_session,
        itinerary_id=iid,
        type="experience",
        title="Tokyo",
        starts_lower=_at(9),
        starts_upper=_at(10),
        lat=_TOKYO[0],
        lng=_TOKYO[1],
    )
    # A flight is governed by schedule, not haversine — even Tokyo->Osaka in
    # 10 min must NOT raise a drive-time flux for the flight leg itself.
    b = await insert_node(
        db_session,
        itinerary_id=iid,
        type="flight",
        title="NRT-ITM",
        starts_lower=_at(10, 10),
        starts_upper=_at(11),
        lat=_OSAKA[0],
        lng=_OSAKA[1],
    )
    output = await standard.run(db_session, itinerary_id=iid)
    assert [f for f in output.findings if f.category == "location_flux"] == []
    assert f"{a}:{b}" not in output.result_extra["drive_times"]
