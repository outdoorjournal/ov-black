"""Tests for the Mt Olympus campaign spine builder.

Focus: the cornerstone anchor node carries the real OV trip's day-by-day
itinerary as an embedded SUBGRAPH (children with ``parent_id`` = the anchor),
so the anchor card reads as the multi-day OV adventure it is, not a single
enriched photo. The generic clone of ``parent_id`` → ``parent_subgraph_id`` at
instantiation is already covered by ``test_templates_service``.

Real-DB integration (like ``test_japan_template``): skipped unless the local
Supabase Postgres is reachable.
"""

from __future__ import annotations

import socket

import pytest
from app.models import TemplateNode
from app.seed_data.olympus_cornerstones import (
    BEAT_STOCK,
    GUIDED_2DAY,
    SYMBOLISM,
    cornerstone_for_nights,
)
from app.services.olympus_template import (
    OLYMPUS_SPINE_SLUGS,
    build_olympus_template,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", 54322))
        except OSError:
            return False
        return True


integration = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


async def _delete_olympus_templates() -> None:
    """Clean slate: drop every Olympus spine template + its cascade."""
    # Stored slugs are the base plus a ``-<content hash>`` suffix, so match by
    # prefix — a bare ``= any(base_slugs)`` would miss every hashed template.
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.card_templates where slug like any(:patterns)"),
                {"patterns": [f"{base}%" for base in OLYMPUS_SPINE_SLUGS.values()]},
            )
    finally:
        await engine.dispose()


def test_beats_are_fully_authored() -> None:
    """Offline contract: every beat carries a description and a valid stock key.

    The stock sets are the beats' imagery (BEAT_STOCK, 3–5 vetted shots per
    kind of moment); a typo'd key would KeyError at template build, and a
    description-less beat renders a bare title card — both caught here without
    a DB.
    """
    for cornerstone in (SYMBOLISM, GUIDED_2DAY):
        for day in cornerstone.days:
            for beat in day.beats:
                assert beat.description, f"beat {beat.title!r} has no description"
                assert beat.stock in BEAT_STOCK, (
                    f"beat {beat.title!r} has unknown stock {beat.stock!r}"
                )
    for category, pool in BEAT_STOCK.items():
        assert 3 <= len(pool) <= 5, f"stock set {category!r} should ship 3-5 images"
        assert all(url.startswith("https://images.unsplash.com/photo-") for url in pool)


@integration
@pytest.mark.asyncio
async def test_travel_day_placeholder_leads_the_spine() -> None:
    """Day 1 is a held travel placeholder; everything else shifts down a day.

    The traveler needs the first day open to fly in, so the spine leads with a
    single free_time card whose note says the day is reserved for travel, the
    cornerstone anchor lands on day 2, and the extension is prefix-sliced one
    day shorter so the trip still fits its nights.
    """
    await _delete_olympus_templates()
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    day_minutes = 24 * 60
    try:
        async with maker() as session:
            nights = 14
            template = await build_olympus_template(session, nights=nights)
            cornerstone = cornerstone_for_nights(nights, longest=max(OLYMPUS_SPINE_SLUGS))
            rows = (
                (
                    await session.execute(
                        select(TemplateNode).where(TemplateNode.template_id == template.id)
                    )
                )
                .scalars()
                .all()
            )
            spine = [n for n in rows if n.parent_id is None]

            travel = next(n for n in spine if n.title == "Travel day — held for your arrival")
            assert travel.type.value == "free_time"
            assert travel.starts_at_offset_minutes is not None
            assert 0 <= travel.starts_at_offset_minutes < day_minutes, "travel owns day 1"
            assert "held open for travel" in travel.metadata_["description"]

            # Everything else starts day 2 or later, and the whole spine still
            # fits the trip frame (depart on day nights+1 at the latest).
            others = [n for n in spine if n.id != travel.id]
            offsets = [n.starts_at_offset_minutes for n in others]
            assert all(off is not None and off >= day_minutes for off in offsets)
            assert max(off for off in offsets if off is not None) < nights * day_minutes

            anchor = next(n for n in spine if n.title == cornerstone.title)
            assert anchor.starts_at_offset_minutes is not None
            assert day_minutes <= anchor.starts_at_offset_minutes < 2 * day_minutes

            # The extension gave up one day to the travel day: its slice is now
            # nights - span - 1, so the 14-night tour closes in the Pelion
            # villages and the old day-14 Thessaloniki closer is sliced off.
            titles = {n.title for n in spine}
            assert "A slow day in the villages" in titles
            assert "Thessaloniki — the northern capital" not in titles
    finally:
        await engine.dispose()
        await _delete_olympus_templates()


@integration
@pytest.mark.asyncio
async def test_cornerstone_lands_as_subgraph_in_template() -> None:
    """The summit anchor gets one child template_node per cornerstone BEAT."""
    await _delete_olympus_templates()
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as session:
            template = await build_olympus_template(session, nights=14)
            cornerstone = cornerstone_for_nights(14, longest=max(OLYMPUS_SPINE_SLUGS))
            assert cornerstone.days, "the 14-night cornerstone must ship baked days"

            rows = (
                (
                    await session.execute(
                        select(TemplateNode).where(TemplateNode.template_id == template.id)
                    )
                )
                .scalars()
                .all()
            )
            # Exactly the cornerstone's beats are nested (parent_id set) — one
            # child per authored beat, a day-child fallback for beat-less days;
            # every other node is top-level spine.
            children = [n for n in rows if n.parent_id is not None]
            expected = sum(len(day.beats) or 1 for day in cornerstone.days)
            assert len(children) == expected

            parent_ids = {n.parent_id for n in children}
            assert len(parent_ids) == 1, "all beat children hang off the single anchor"
            anchor = next(n for n in rows if n.id == next(iter(parent_ids)))
            assert anchor.parent_id is None, "the anchor itself is top-level spine"

            # Children are unscheduled (the anchor owns the time slot) and carry
            # the shared subgraph_day metadata the journey view reads; every
            # cornerstone day is covered, and authored beats carry their
            # inferred clock time + duration.
            day_indexes: set[int] = set()
            for child in children:
                assert child.starts_at_offset_minutes is None
                subgraph_day = child.metadata_.get("subgraph_day")
                assert subgraph_day, "child carries subgraph_day meta"
                day_indexes.add(subgraph_day["index"])
            assert day_indexes == {day.day for day in cornerstone.days}
            beat_children = [n for n in children if "hhmm" in n.metadata_["subgraph_day"]]
            assert len(beat_children) == sum(len(day.beats) for day in cornerstone.days)
            # Each beat carries its authored card kind — a dinner is a meal, a
            # transfer a drive, an open morning free_time — not a blanket
            # "experience" (matched by title, which is unique per beat).
            beat_kinds = {
                beat.title: beat.node_type for day in cornerstone.days for beat in day.beats
            }
            for child in beat_children:
                meta = child.metadata_["subgraph_day"]
                assert isinstance(meta.get("duration_minutes"), int)
                assert child.metadata_["snapshot"]["title"] == child.title
                # Every beat wears its own stock hero + card description.
                ambient = child.metadata_.get("ambient_image")
                assert isinstance(ambient, str) and ambient.startswith(
                    "https://images.unsplash.com/photo-"
                )
                assert child.metadata_["snapshot"]["cover_image"] == ambient
                assert child.metadata_.get("description"), "beat carries a card description"
                assert child.type == beat_kinds[child.title], (
                    f"beat {child.title!r} landed as {child.type} not {beat_kinds[child.title]}"
                )
            # Rotation: beats of one category get DIFFERENT images until the
            # set wraps — e.g. the three dinners must not share a shot.
            ambients = [c.metadata_["ambient_image"] for c in beat_children]
            assert len(set(ambients)) > len(BEAT_STOCK) // 2, "stock rotation looks broken"
    finally:
        await engine.dispose()
        await _delete_olympus_templates()
