"""Itinerary change replay (Wave F) — pure diff math + merged history paging."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.changes import (
    diff_changed_keys,
    load_itinerary_changes,
    next_changes_cursor,
)
from app.services.pagination import decode_cursor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── pure: the changed-keys diff ──────────────────────────────────────────────


def test_diff_reports_changed_added_and_removed_keys() -> None:
    before = {"title": "Old", "status": "pending", "kept": 1}
    after = {"title": "New", "status": "pending", "added": True}
    assert diff_changed_keys(before, after) == ["added", "kept", "title"]


def test_diff_handles_missing_sides() -> None:
    assert diff_changed_keys(None, {"title": "Born"}) == ["title"]
    assert diff_changed_keys({"title": "Gone"}, None) == ["title"]
    assert diff_changed_keys(None, None) == []


def test_diff_is_order_stable() -> None:
    assert diff_changed_keys({"b": 1, "a": 1}, {"b": 2, "a": 2}) == ["a", "b"]


# ── integration ──────────────────────────────────────────────────────────────


async def _seed_node_history(
    s: AsyncSession, *, itinerary_id: uuid.UUID, occurred_at: datetime, title: str
) -> None:
    await s.execute(
        text(
            """
            insert into public.node_history
              (node_id, itinerary_id, op, actor_kind, before, after, occurred_at)
            values (:nid, :iid, 'update', 'advisor', cast(:b as jsonb), cast(:a as jsonb), :at)
            """
        ),
        {
            "nid": uuid.uuid4(),
            "iid": itinerary_id,
            "b": '{"status": "pending"}',
            "a": f'{{"status": "approved", "title": "{title}"}}',
            "at": occurred_at,
        },
    )
    await s.commit()


async def _seed_edge_history(
    s: AsyncSession, *, itinerary_id: uuid.UUID, occurred_at: datetime
) -> None:
    await s.execute(
        text(
            """
            insert into public.edge_history
              (edge_id, itinerary_id, op, actor_kind, before, after, occurred_at)
            values (:eid, :iid, 'insert', 'agent', null, cast(:a as jsonb), :at)
            """
        ),
        {"eid": uuid.uuid4(), "iid": itinerary_id, "a": '{"type": "sequence"}', "at": occurred_at},
    )
    await s.commit()


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        itin = await insert_itinerary(s, title="Replay trip")
        other = await insert_itinerary(s, title="Other trip")
        base = datetime.now(UTC)
        # Three node beats + one edge beat SHARING base-1m with a node beat —
        # the cross-table tie the cursor must not skip or duplicate.
        await _seed_node_history(
            s, itinerary_id=itin, occurred_at=base - timedelta(minutes=3), title="First"
        )
        await _seed_node_history(
            s, itinerary_id=itin, occurred_at=base - timedelta(minutes=1), title="Tied"
        )
        await _seed_edge_history(s, itinerary_id=itin, occurred_at=base - timedelta(minutes=1))
        await _seed_node_history(s, itinerary_id=itin, occurred_at=base, title="Latest")
        # Noise on another itinerary that must never appear.
        await _seed_node_history(s, itinerary_id=other, occurred_at=base, title="Foreign")
    try:
        yield SimpleNamespace(maker=maker, itin=itin)
    finally:
        await engine.dispose()


@integration
async def test_replay_is_newest_first_and_projected() -> None:
    async with _world() as w, w.maker() as s:
        changes = await load_itinerary_changes(s, itinerary_id=w.itin, limit=50)
        assert len(changes) == 4
        assert changes[0].title == "Latest"
        assert changes[0].status_before == "pending"
        assert changes[0].status_after == "approved"
        assert changes[0].changed_keys == ["status", "title"]
        assert {c.entity for c in changes} == {"node", "edge"}
        # The edge beat projects no title/status but does carry changed keys.
        edge = next(c for c in changes if c.entity == "edge")
        assert edge.title is None
        assert edge.changed_keys == ["type"]


@integration
async def test_replay_pages_through_the_cross_table_tie() -> None:
    async with _world() as w, w.maker() as s:
        full = await load_itinerary_changes(s, itinerary_id=w.itin, limit=50)
        walked: list[str] = []
        cursor: dict[str, object] | None = None
        for _ in range(6):
            page = await load_itinerary_changes(s, itinerary_id=w.itin, limit=1, cursor=cursor)
            if not page:
                break
            walked.extend(c.id for c in page)
            token = next_changes_cursor(page, 1)
            assert token is not None
            cursor = decode_cursor(token)
        assert walked == [c.id for c in full]
        assert len(walked) == len(set(walked))


@integration
async def test_entity_filter_narrows_the_replay() -> None:
    async with _world() as w, w.maker() as s:
        nodes = await load_itinerary_changes(s, itinerary_id=w.itin, limit=50, entity="node")
        edges = await load_itinerary_changes(s, itinerary_id=w.itin, limit=50, entity="edge")
        assert {c.entity for c in nodes} == {"node"}
        assert {c.entity for c in edges} == {"edge"}
        assert len(nodes) == 3
        assert len(edges) == 1
