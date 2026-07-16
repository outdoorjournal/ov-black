"""Phase 2 (doc/itin-time.md): adapter round-trips and the 0055 backfill.

The integration half runs against the migrated local Supabase: it exercises the
``kernel_backfill_schedule()`` SQL function on freshly inserted legacy-shaped
rows, then runs the dual-read sweep that gates Phase 3 — every scheduled node's
canonical columns must resolve to exactly the stored ``starts_at``.
"""

from __future__ import annotations

import socket
import uuid
from datetime import date, time

import pytest
from app.kernel import (
    AbsoluteStamp,
    KernelViolation,
    PinnedSchedule,
    columns_from_schedule,
    relative,
    schedule_from_columns,
)
from app.services.kernel_backfill_verify import verify_dual_read
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322

ATHENS = "Europe/Athens"


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


# ── adapter unit tests ───────────────────────────────────────────────────────


class TestAdapterRoundTrip:
    def test_relative_with_end(self):
        schedule = relative(4, time(9, 0), ATHENS, duration_minutes=120)
        assert schedule_from_columns(**columns_from_schedule(schedule)) == schedule

    def test_pinned_without_end(self):
        schedule = PinnedSchedule(start=AbsoluteStamp(date(2026, 8, 14), time(10, 3), ATHENS))
        assert schedule_from_columns(**columns_from_schedule(schedule)) == schedule

    def test_none_round_trips(self):
        columns = columns_from_schedule(None)
        assert columns["schedule_kind"] is None
        assert schedule_from_columns(**columns) is None

    def test_relative_carrying_a_date_is_malformed(self):
        with pytest.raises(KernelViolation) as exc:
            schedule_from_columns(
                schedule_kind="relative",
                start_day_offset=1,
                start_date=date(2026, 8, 1),
                start_wall_time=time(9, 0),
                start_tz=ATHENS,
            )
        assert exc.value.code == "malformed_schedule_row"

    def test_fields_without_kind_are_malformed(self):
        with pytest.raises(KernelViolation):
            schedule_from_columns(
                schedule_kind=None,
                start_day_offset=1,
                start_date=None,
                start_wall_time=None,
                start_tz=None,
            )


# ── integration: the SQL backfill + the dual-read gate ───────────────────────


@pytest.fixture
async def db_session():
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _insert_legacy_trip(session: AsyncSession, *, anchor: date | None, status: str) -> str:
    """An itinerary + one legacy-shaped scheduled node (starts_at + metadata
    offset, no kernel columns), as every pre-0055 write produced."""
    itinerary_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    await session.execute(
        text(
            "insert into itineraries (id, title, anchor_date)"
            " values (:iid, 'kernel-backfill-test', :anchor)"
        ),
        {"iid": itinerary_id, "anchor": anchor},
    )
    await session.execute(
        text(
            "insert into nodes (id, itinerary_id, type, status, title, starts_at, metadata)"
            " values (:nid, :iid, 'experience', cast(:status as node_status), 'Backfill probe',"
            " tstzrange('2026-08-04T06:00:00Z', '2026-08-04T08:00:00Z', '[)'),"
            " jsonb_build_object('start_time', '2026-08-04T09:00:00+03:00',"
            "                    'tz_offset_minutes', 180))"
        ),
        {"nid": node_id, "iid": itinerary_id, "status": status},
    )
    await session.commit()
    return node_id


async def _cleanup(session: AsyncSession, node_id: str) -> None:
    await session.execute(
        text("delete from itineraries where id = (select itinerary_id from nodes where id = :nid)"),
        {"nid": node_id},
    )
    await session.commit()


@integration
async def test_backfill_converts_a_pending_row_to_relative(db_session: AsyncSession):
    node_id = await _insert_legacy_trip(db_session, anchor=date(2026, 8, 1), status="pending")
    try:
        await db_session.execute(text("select * from kernel_backfill_schedule()"))
        await db_session.commit()
        row = (
            await db_session.execute(
                text(
                    "select schedule_kind, start_day_offset, start_wall_time::text,"
                    " start_tz, end_day_offset, end_wall_time::text"
                    " from nodes where id = :nid"
                ),
                {"nid": node_id},
            )
        ).one()
        # Aug 4 09:00 at +03:00 with anchor Aug 1 = Day 4 (offset 3), 9am wall.
        assert row.schedule_kind == "relative"
        assert row.start_day_offset == 3
        assert row.start_wall_time == "09:00:00"
        assert row.start_tz == "Etc/GMT-3"  # POSIX sign: Etc/GMT-3 == UTC+3
        assert row.end_day_offset == 3
        assert row.end_wall_time == "11:00:00"
    finally:
        await _cleanup(db_session, node_id)


@integration
async def test_backfill_pins_committed_and_anchorless_rows(db_session: AsyncSession):
    booked = await _insert_legacy_trip(db_session, anchor=date(2026, 8, 1), status="booked")
    anchorless = await _insert_legacy_trip(db_session, anchor=None, status="pending")
    try:
        await db_session.execute(text("select * from kernel_backfill_schedule()"))
        await db_session.commit()
        for node_id in (booked, anchorless):
            row = (
                await db_session.execute(
                    text(
                        "select schedule_kind, start_date::text, start_wall_time::text"
                        " from nodes where id = :nid"
                    ),
                    {"nid": node_id},
                )
            ).one()
            assert row.schedule_kind == "pinned"
            assert row.start_date == "2026-08-04"
            assert row.start_wall_time == "09:00:00"
    finally:
        await _cleanup(db_session, booked)
        await _cleanup(db_session, anchorless)


@integration
async def test_dual_read_gate_is_clean(db_session: AsyncSession):
    """The Phase 3 cutover pattern: re-run the (idempotent) backfill to pick up
    rows the legacy write path produced since migration, then demand an exact
    dual read across the entire database."""
    await db_session.execute(text("select * from kernel_backfill_schedule()"))
    await db_session.commit()
    report = await verify_dual_read(db_session)
    assert report.scheduled > 0
    assert report.clean, f"dual-read failures: {report.samples}"
    assert report.verified == report.scheduled
