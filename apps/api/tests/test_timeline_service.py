"""Tests for the linearization service (Phase 3).

Layered:

1. **Pure dataclass shape** — TimelineView round-trips an empty cards
   list without touching the DB.
2. **Integration** (gated on local Supabase) — covers the eight rules
   that make linearization the one place that knows the timeline:
   ordering by ``starts_at`` lower bound, time-window overlap filter,
   selected-branch toggle, structural-role exclusion, party filter
   (with the implicit "no parties = all" default), attached-note
   nesting, and a real-trip Japan-fixture round-trip that proves the
   service walks production-shaped data correctly.

Setup is intentionally raw-SQL: Phase 3 is a read service, so writes
in test setup don't go through Phase 4's not-yet-extended ``add_node``
service. Going through SQL also exercises the Phase 1 columns
(``starts_at``, ``role``, ``is_selected_alt``, ``attached_to_node_id``)
end-to-end.
"""

from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.seed_data.japan_itinerary import FixtureItem, all_items
from app.services.timeline import Card, TimelineView, linearize
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322


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


# ── Pure-dataclass smoke ──────────────────────────────────────────────


def test_timeline_view_empty_shape() -> None:
    """No DB round-trip — just confirms the dataclasses compose cleanly."""
    iid = uuid.uuid4()
    view = TimelineView(itinerary_id=iid, party_id=None, cards=[])
    assert view.itinerary_id == iid
    assert view.party_id is None
    assert view.cards == []


# ── Integration setup ─────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _create_itinerary(session: AsyncSession, *, title: str) -> uuid.UUID:
    iid = uuid.uuid4()
    await session.execute(
        text("insert into public.itineraries (id, title) values (:id, :t)"),
        {"id": iid, "t": title},
    )
    await session.commit()
    return iid


async def _insert_node(
    session: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    type: str,
    title: str = "",
    starts_lower: datetime | None = None,
    starts_upper: datetime | None = None,
    role: str | None = None,
    is_selected_alt: bool = True,
    attached_to_node_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Raw insert that lets the caller set every Phase-1 column."""
    nid = uuid.uuid4()
    sql = text(
        """
        insert into public.nodes (
            id, itinerary_id, type, title, starts_at, role,
            is_selected_alt, attached_to_node_id, metadata
        )
        values (
            :id, :iid, cast(:type as public.node_type), :title,
            case when cast(:lo as timestamptz) is null
                  and cast(:hi as timestamptz) is null then null
                 else tstzrange(
                     cast(:lo as timestamptz),
                     cast(:hi as timestamptz),
                     '[)'
                 ) end,
            case when cast(:role as text) is null then null
                 else cast(:role as public.node_role) end,
            :sel, cast(:att as uuid), cast(:meta as jsonb)
        )
        """
    )
    await session.execute(
        sql,
        {
            "id": nid,
            "iid": itinerary_id,
            "type": type,
            "title": title,
            "lo": starts_lower,
            "hi": starts_upper,
            "role": role,
            "sel": is_selected_alt,
            "att": attached_to_node_id,
            "meta": json.dumps(metadata or {}),
        },
    )
    await session.commit()
    return nid


async def _create_party(session: AsyncSession, *, itinerary_id: uuid.UUID, label: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await session.execute(
        text("insert into public.parties (id, itinerary_id, label) values (:id, :iid, :l)"),
        {"id": pid, "iid": itinerary_id, "l": label},
    )
    await session.commit()
    return pid


async def _attach_party(session: AsyncSession, *, node_id: uuid.UUID, party_id: uuid.UUID) -> None:
    await session.execute(
        text("insert into public.node_parties (node_id, party_id) values (:n, :p)"),
        {"n": node_id, "p": party_id},
    )
    await session.commit()


async def _cleanup_itinerary(itinerary_id: uuid.UUID) -> None:
    """Drop the test itinerary on a fresh engine so rollback-wrecked
    sessions can't leak. Cascades take care of nodes / edges /
    parties / node_parties / attached notes via FK.
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.node_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.edge_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
    finally:
        await engine.dispose()


def _at(*, hour: int, minute: int = 0, day: int = 20) -> datetime:
    """Tokyo-time datetime helper used by the integration tests."""
    return datetime(2024, 6, day, hour, minute, tzinfo=timezone(timedelta(hours=9)))


# ── Integration tests ────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_empty_itinerary_returns_empty_view(
    db_session: AsyncSession,
) -> None:
    iid = await _create_itinerary(db_session, title="empty")
    try:
        view = await linearize(db_session, itinerary_id=iid)
        assert view.itinerary_id == iid
        assert view.cards == []
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_orders_cards_by_starts_at_lower_bound(
    db_session: AsyncSession,
) -> None:
    """Three nodes inserted out-of-order come back in starts_at order."""
    iid = await _create_itinerary(db_session, title="order")
    try:
        # Insert in 09:00, 07:00, 13:00 order; expect 07, 09, 13.
        n_nine = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="nine",
            starts_lower=_at(hour=9),
            starts_upper=_at(hour=10),
        )
        n_seven = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="seven",
            starts_lower=_at(hour=7),
            starts_upper=_at(hour=8),
        )
        n_thirteen = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="meal",
            title="thirteen",
            starts_lower=_at(hour=13),
            starts_upper=_at(hour=14),
        )

        view = await linearize(db_session, itinerary_id=iid)
        ids = [c.node_id for c in view.cards]
        positions = [c.position for c in view.cards]
        assert ids == [n_seven, n_nine, n_thirteen]
        assert positions == [0, 1, 2]
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_time_window_filter_keeps_overlapping_nodes(
    db_session: AsyncSession,
) -> None:
    """Half-open [t_from, t_to) overlap test — straddling ranges count."""
    iid = await _create_itinerary(db_session, title="window")
    try:
        early = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="early",
            starts_lower=_at(hour=6),
            starts_upper=_at(hour=8),
        )
        mid = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="mid",
            starts_lower=_at(hour=11),
            starts_upper=_at(hour=12),
        )
        late = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="late",
            starts_lower=_at(hour=17),
            starts_upper=_at(hour=19),
        )

        view = await linearize(
            db_session,
            itinerary_id=iid,
            t_from=_at(hour=10),
            t_to=_at(hour=15),
        )
        ids = [c.node_id for c in view.cards]
        # `early` ends at 08:00 → outside; `late` starts at 17 → outside.
        # `mid` strictly inside; included.
        assert ids == [mid]
        assert early not in ids and late not in ids
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_selected_branches_only_drops_unselected(
    db_session: AsyncSession,
) -> None:
    """is_selected_alt=False rows are dropped by default."""
    iid = await _create_itinerary(db_session, title="branches")
    try:
        chosen = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="chosen",
            starts_lower=_at(hour=10),
            starts_upper=_at(hour=11),
            is_selected_alt=True,
        )
        rejected = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="rejected",
            starts_lower=_at(hour=10),
            starts_upper=_at(hour=11),
            is_selected_alt=False,
        )

        view_default = await linearize(db_session, itinerary_id=iid)
        ids_default = {c.node_id for c in view_default.cards}
        assert ids_default == {chosen}

        # Renderer wanting to show all branches flips the flag.
        view_all = await linearize(db_session, itinerary_id=iid, selected_branches_only=False)
        ids_all = {c.node_id for c in view_all.cards}
        assert ids_all == {chosen, rejected}
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_structural_role_excluded_by_default(
    db_session: AsyncSession,
) -> None:
    """Destinations / termini sit on the role axis and don't render as
    leaf cards by default. Renderers wanting headers flip the flag.
    """
    iid = await _create_itinerary(db_session, title="role")
    try:
        regular = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="regular",
            starts_lower=_at(hour=10),
            starts_upper=_at(hour=11),
        )
        marker = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="destination",
            title="Tokyo region anchor",
            starts_lower=_at(hour=8),
            starts_upper=_at(hour=23),
            role="destination",
        )

        view_default = await linearize(db_session, itinerary_id=iid)
        assert {c.node_id for c in view_default.cards} == {regular}

        view_with = await linearize(db_session, itinerary_id=iid, include_structural=True)
        assert {c.node_id for c in view_with.cards} == {regular, marker}
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_party_filter_implicit_all_default(
    db_session: AsyncSession,
) -> None:
    """A node with no node_parties rows is "all parties" — visible to
    every party_id filter. A node with explicit party rows is only
    visible to those parties.
    """
    iid = await _create_itinerary(db_session, title="parties")
    try:
        kids_party = await _create_party(db_session, itinerary_id=iid, label="kids")
        adults_party = await _create_party(db_session, itinerary_id=iid, label="adults")

        for_all = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="for_all",
            starts_lower=_at(hour=9),
            starts_upper=_at(hour=10),
        )
        kids_only = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="kids_only",
            starts_lower=_at(hour=10),
            starts_upper=_at(hour=11),
        )
        await _attach_party(db_session, node_id=kids_only, party_id=kids_party)

        # No filter → both visible.
        view_no = await linearize(db_session, itinerary_id=iid)
        assert {c.node_id for c in view_no.cards} == {for_all, kids_only}

        # Kids filter → both visible (default-all + kids-only).
        view_kids = await linearize(db_session, itinerary_id=iid, party_id=kids_party)
        assert {c.node_id for c in view_kids.cards} == {for_all, kids_only}

        # Adults filter → only the all-default; kids-only excluded.
        view_adults = await linearize(db_session, itinerary_id=iid, party_id=adults_party)
        assert {c.node_id for c in view_adults.cards} == {for_all}
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_attached_notes_nested_under_host(
    db_session: AsyncSession,
) -> None:
    """Attached notes never appear in the main list — they nest under
    the host card's ``attached_notes`` field, ordered by created_at.
    """
    iid = await _create_itinerary(db_session, title="notes")
    try:
        host = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="experience",
            title="host",
            starts_lower=_at(hour=10),
            starts_upper=_at(hour=11),
        )
        # Attached note: no starts_at, attached_to_node_id set.
        note_one = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="note",
            title="first attached",
            attached_to_node_id=host,
        )
        note_two = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="note",
            title="second attached",
            attached_to_node_id=host,
        )
        # Free-standing note: own starts_at, no host. Goes in main list.
        free_note = await _insert_node(
            db_session,
            itinerary_id=iid,
            type="note",
            title="standalone",
            starts_lower=_at(hour=12),
            starts_upper=_at(hour=12, minute=30),
        )

        view = await linearize(db_session, itinerary_id=iid)
        main_ids = [c.node_id for c in view.cards]
        # Only host + free-standing are in the main list.
        assert main_ids == [host, free_note]

        host_card = view.cards[0]
        attached_ids = [n.node_id for n in host_card.attached_notes]
        assert attached_ids == [note_one, note_two]
        # Position within the attached group is 0-indexed.
        assert [n.position for n in host_card.attached_notes] == [0, 1]
        # Free-standing note has no attached notes.
        assert view.cards[1].attached_notes == []
    finally:
        await _cleanup_itinerary(iid)


@integration
@pytest.mark.asyncio
async def test_japan_fixture_linearizes_in_chronological_order(
    db_session: AsyncSession,
) -> None:
    """End-to-end: insert every Japan fixture item, linearize, assert
    the order matches the fixture's chronological sequence.
    """
    iid = await _create_itinerary(db_session, title="japan-trip")
    try:
        items = all_items()
        node_id_by_hint: dict[str, uuid.UUID] = {}
        for item in items:
            ends_at = item.starts_at + timedelta(minutes=item.duration_minutes)
            metadata = item.attrs.model_dump(mode="json", exclude_none=True)
            nid = await _insert_node(
                db_session,
                itinerary_id=iid,
                type=item.attrs.kind,
                title=item.title,
                starts_lower=item.starts_at,
                starts_upper=ends_at,
                metadata=metadata,
            )
            node_id_by_hint[item.id_hint] = nid

        view = await linearize(db_session, itinerary_id=iid)
        # The fixture iterates day-by-day, items in declared order;
        # each item has a strictly-increasing starts_at, so the
        # linearized order must match the fixture order exactly.
        expected_titles = [item.title for item in items]
        actual_titles = [card.title for card in view.cards]
        assert actual_titles == expected_titles, (
            f"linearization order drift\nexpected: {expected_titles}\nactual:   {actual_titles}"
        )

        # Spot-check: the day-05 Shinkansen card carries the parsed
        # train attributes (Cards Style Guide signature detail).
        shinkansen = next(c for c in view.cards if c.title == "Shinkansen Hikari #635 → Kyoto")
        assert shinkansen.attrs.kind == "train"
        # Mt. Fuji scenery callout survives the round-trip.
        callouts = getattr(shinkansen.attrs, "scenery_callouts", [])
        assert len(callouts) == 1
        assert callouts[0].what == "Mt. Fuji"
    finally:
        await _cleanup_itinerary(iid)


def _ensure_unused_imports(_x: FixtureItem | Card) -> None:  # pragma: no cover
    """Keep the FixtureItem / Card imports flagged as used by static
    analysis even when the fixture / Card return type is only consumed
    as a positional type. Pure no-op."""
