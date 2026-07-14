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
from app.seed_data.olympus_cornerstones import cornerstone_for_nights
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
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.card_templates where slug = any(:slugs)"),
                {"slugs": list(OLYMPUS_SPINE_SLUGS.values())},
            )
    finally:
        await engine.dispose()


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
            for child in beat_children:
                meta = child.metadata_["subgraph_day"]
                assert isinstance(meta.get("duration_minutes"), int)
                assert child.metadata_["snapshot"]["title"] == child.title
    finally:
        await engine.dispose()
        await _delete_olympus_templates()
