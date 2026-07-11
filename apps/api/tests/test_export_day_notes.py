"""Day notes: fallback rules, prompt redaction, cache + auto-fill semantics."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import date

import pytest_asyncio
from app.config import Settings
from app.models import DayNotesSource, ItineraryDayNotes
from app.services.export import day_notes as dn
from app.services.export.day_notes import (
    MockDayNotesClient,
    build_day_notes_prompt,
    compute_nodes_hash,
    ensure_day_notes,
    fallback_notes,
    parse_llm_notes,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._export_fixtures import make_day, make_item, make_trip
from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── Deterministic fallback ───────────────────────────────────────────────────


def test_fallback_detects_timezone_shift() -> None:
    prev = make_day(date(2026, 6, 1), (make_item(start="2026-06-01T09:00:00-07:00"),))
    today = make_day(date(2026, 6, 2), (make_item(start="2026-06-02T09:00:00+09:00"),))
    out = fallback_notes(today, prev)
    assert any("time zone" in t.lower() for t in out["tips"])
    assert any("16h" in t for t in out["tips"])  # -7 → +9 is +16h


def test_fallback_packing_hints_by_type_and_altitude() -> None:
    day = make_day(
        date(2026, 6, 1),
        (
            make_item(type="flight", title="Flight to Cusco"),
            make_item(type="boat", title="Lake crossing"),
            make_item(type="walk", title="Long hike", duration_minutes=120),
            make_item(type="experience", title="Summit", altitude_m=3400),
        ),
    )
    bring = " ".join(fallback_notes(day, None)["bring"]).lower()
    assert "documents" in bring
    assert "waterproof" in bring
    assert "shoes" in bring
    assert "altitude" in bring


def test_fallback_hotel_change_and_early_start() -> None:
    prev = make_day(date(2026, 6, 1), (make_item(),), night_hotel="Hotel A")
    today = make_day(
        date(2026, 6, 2),
        (make_item(start="2026-06-02T06:30:00+09:00"),),
        night_hotel="Hotel B",
    )
    tips = " ".join(fallback_notes(today, prev)["tips"]).lower()
    assert "change hotels" in tips
    assert "early start" in tips


# ── Prompt building + parsing ────────────────────────────────────────────────


def test_build_prompt_is_graph_only_no_dossier_leak() -> None:
    day = make_day(date(2026, 6, 1), (make_item(title="Fushimi Inari"),))
    trip = make_trip((day,), title="Kyoto", brief="gardens and food")
    prompt = build_day_notes_prompt(
        trip.days, [date(2026, 6, 1)], title=trip.title, brief=trip.brief
    )
    assert "Fushimi Inari" in prompt
    assert "gardens and food" in prompt
    # A dossier-shaped sentinel is never in scope of the builder's inputs.
    assert "NET_WORTH_SECRET" not in prompt


def test_day_notes_module_imports_no_traveler_context() -> None:
    # The redaction guarantee is structural: this module must not IMPORT any
    # dossier / OSINT / profile-fact / traveler-context code. Inspect the
    # module's actual import statements (not raw text — the redaction docstring
    # legitimately names those tiers).
    import ast

    forbidden = ("traveler_context", "dossier", "osint", "profile_fact")
    src = dn.__file__
    assert src is not None
    with open(src) as fh:
        tree = ast.parse(fh.read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    for module in imported:
        assert not any(f in module for f in forbidden), module


def test_parse_llm_notes_tolerates_prose_and_rejects_junk() -> None:
    good = 'Here you go:\n{"2026-06-01": {"bring": ["Hat"], "tips": ["Nap"]}}\nThanks!'
    parsed = parse_llm_notes(good, [date(2026, 6, 1)])
    assert parsed == {date(2026, 6, 1): {"bring": ["Hat"], "tips": ["Nap"]}}
    assert parse_llm_notes("no json here", [date(2026, 6, 1)]) is None
    assert parse_llm_notes('{"other": 1}', [date(2026, 6, 1)]) is None


def test_compute_nodes_hash_changes_with_content() -> None:
    day_a = make_day(date(2026, 6, 1), (make_item(title="A"),))
    day_b = make_day(date(2026, 6, 1), (make_item(title="B"),))
    assert compute_nodes_hash(day_a, None) != compute_nodes_hash(day_b, None)
    # Previous-day zone is part of the fingerprint.
    assert compute_nodes_hash(day_a, None) != compute_nodes_hash(day_a, 540)


# ── Auto-fill against the DB ─────────────────────────────────────────────────


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


def _trip() -> object:
    d1 = make_day(date(2026, 6, 1), (make_item(title="A", start="2026-06-01T09:00:00+09:00"),))
    d2 = make_day(date(2026, 6, 2), (make_item(title="B", start="2026-06-02T09:00:00+09:00"),))
    return make_trip((d1, d2))


def _enabled() -> Settings:
    return Settings(export_day_notes_enabled=True)


def _disabled() -> Settings:
    return Settings(export_day_notes_enabled=False)


@integration
async def test_ensure_day_notes_cache_miss_then_hit(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes cache")
    try:
        trip = _trip()
        client = MockDayNotesClient(
            [
                json.dumps(
                    {
                        "2026-06-01": {"bring": ["Hat"], "tips": ["Nap"]},
                        "2026-06-02": {"bring": ["Boots"], "tips": ["Hydrate"]},
                    }
                )
            ]
        )
        result = await ensure_day_notes(
            db_session,
            iid,
            trip,
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        assert len(client.prompts) == 1  # miss → one call
        assert result[date(2026, 6, 1)]["bring"] == ["Hat"]

        # Repeat export → all hashes match → zero calls.
        client2 = MockDayNotesClient(["{}"])
        result2 = await ensure_day_notes(
            db_session,
            iid,
            trip,
            settings=_enabled(),
            client=client2,  # type: ignore[arg-type]
        )
        assert client2.prompts == []
        assert result2[date(2026, 6, 2)]["bring"] == ["Boots"]

        rows = (
            (
                await db_session.execute(
                    text("select source from public.itinerary_day_notes where itinerary_id = :i"),
                    {"i": iid},
                )
            )
            .scalars()
            .all()
        )
        assert set(rows) == {DayNotesSource.llm.value}
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)


@integration
async def test_ensure_day_notes_content_change_regenerates(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes regen")
    try:
        client = MockDayNotesClient(['{"2026-06-01": {"bring": ["Hat"], "tips": []}}'] * 3)
        d1 = make_day(date(2026, 6, 1), (make_item(title="A", start="2026-06-01T09:00:00+09:00"),))
        await ensure_day_notes(
            db_session,
            iid,
            make_trip((d1,)),
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        assert len(client.prompts) == 1

        # Change the day's content → hash miss → regenerate that day.
        d1b = make_day(
            date(2026, 6, 1), (make_item(title="Changed", start="2026-06-01T09:00:00+09:00"),)
        )
        await ensure_day_notes(
            db_session,
            iid,
            make_trip((d1b,)),
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        assert len(client.prompts) == 2
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)


@integration
async def test_advisor_row_never_regenerated(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes advisor")
    try:
        db_session.add(
            ItineraryDayNotes(
                itinerary_id=iid,
                day_date=date(2026, 6, 1),
                source=DayNotesSource.advisor.value,
                nodes_hash=None,
                content={"bring": ["Advisor pick"], "tips": []},
            )
        )
        await db_session.commit()

        client = MockDayNotesClient(['{"2026-06-02": {"bring": ["B"], "tips": []}}'])
        result = await ensure_day_notes(
            db_session,
            iid,
            _trip(),
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        # Advisor day used verbatim; only the OTHER day is generated.
        assert result[date(2026, 6, 1)]["bring"] == ["Advisor pick"]
        assert len(client.prompts) == 1
        targets_line = next(
            ln for ln in client.prompts[0].splitlines() if "dates only:" in ln
        )
        assert "2026-06-01" not in targets_line  # advisor day excluded from generation
        assert "2026-06-02" in targets_line
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)


@integration
async def test_ensure_day_notes_falls_back_when_disabled(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes fallback")
    try:
        d1 = make_day(date(2026, 6, 1), (make_item(type="flight", title="Fly"),))
        result = await ensure_day_notes(db_session, iid, make_trip((d1,)), settings=_disabled())
        assert any("documents" in b.lower() for b in result[date(2026, 6, 1)]["bring"])
        rows = (
            (
                await db_session.execute(
                    text("select source from public.itinerary_day_notes where itinerary_id = :i"),
                    {"i": iid},
                )
            )
            .scalars()
            .all()
        )
        assert set(rows) == {DayNotesSource.fallback.value}
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)


@integration
async def test_ensure_day_notes_falls_back_when_llm_raises(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes raise")
    try:
        client = MockDayNotesClient(raise_on_generate=dn.DayNotesError("boom"))
        d1 = make_day(date(2026, 6, 1), (make_item(type="boat", title="Cross"),))
        result = await ensure_day_notes(
            db_session,
            iid,
            make_trip((d1,)),
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        assert any("waterproof" in b.lower() for b in result[date(2026, 6, 1)]["bring"])
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)


@integration
async def test_ensure_day_notes_force_regenerate(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="notes force")
    try:
        client = MockDayNotesClient(['{"2026-06-01": {"bring": ["A"], "tips": []}}'] * 5)
        d1 = make_day(date(2026, 6, 1), (make_item(title="A", start="2026-06-01T09:00:00+09:00"),))
        trip = make_trip((d1,))
        await ensure_day_notes(
            db_session,
            iid,
            trip,
            settings=_enabled(),
            client=client,  # type: ignore[arg-type]
        )
        # Fresh hash — a normal export wouldn't call again, but force does.
        await ensure_day_notes(
            db_session,
            iid,
            trip,
            settings=_enabled(),
            client=client,
            force_regenerate=True,  # type: ignore[arg-type]
        )
        assert len(client.prompts) == 2
    finally:
        # ensure_day_notes writes without committing (a service — the route
        # commits). Roll back so the separate-connection _cleanup isn't blocked
        # by the session's uncommitted itinerary_day_notes row locks.
        await db_session.rollback()
        await _cleanup(iid)
