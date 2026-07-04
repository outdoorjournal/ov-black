"""M006/PS2 — the Artemis session LIST.

Two layers:
  - a plain unit test for the auto-title derivation (runs everywhere);
  - ``@integration`` tests against the local Supabase (127.0.0.1:54322) that
    exercise the real query behaviour the fake session can't model: scope-aware
    reuse (no more re-pinning), ``force_new``, scope-filtered listing, the
    traveler↔advisor audience gate, and rename/archive. These skip when the
    local DB isn't up (CI has no Postgres), mirroring the other integration
    suites.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.models import SessionAudience
from app.services.agent import (
    ActorContext,
    SessionOutcome,
    _derive_session_title,
    list_sessions,
    open_or_reuse_session,
    patch_session,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── unit: auto-title derivation ─────────────────────────────────────────────


def test_derive_session_title_collapses_and_truncates() -> None:
    assert _derive_session_title("  Plan   a   trip ") == "Plan a trip"
    long = "A quiet week somewhere coastal with hot springs and slow mornings please"
    title = _derive_session_title(long, max_length=30)
    assert len(title) <= 31  # 30 + the ellipsis
    assert title.endswith("…")
    assert " " not in title[-2:]  # cut on a word boundary, not mid-word


# ── integration: real scope / reuse / list / patch behaviour ────────────────


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    """A seeded client (advisor owner + traveler auth link) + two itineraries."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    cid = uuid.uuid4()
    owner = uuid.uuid4()
    traveler = uuid.uuid4()
    async with maker() as s:
        # owner_id / auth_user_id FK into auth.users — seed both principals.
        for uid, label in ((owner, "owner"), (traveler, "traveler")):
            await s.execute(
                text(
                    "insert into auth.users (id, email, aud, role, instance_id) "
                    "values (:id, :email, 'authenticated', 'authenticated', "
                    "'00000000-0000-0000-0000-000000000000')"
                ),
                {"id": uid, "email": f"ps2-{label}-{uid}@x.com"},
            )
        await s.execute(
            text(
                "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
                "values (:id, :o, :a, :n, :e)"
            ),
            {"id": cid, "o": owner, "a": traveler, "n": "PS2 Client", "e": f"ps2-{cid}@x.com"},
        )
        await s.commit()
        itin_a = await insert_itinerary(s, title="Trip A", created_by=owner, client_id=cid)
        itin_b = await insert_itinerary(s, title="Trip B", created_by=owner, client_id=cid)
        await s.commit()
    world = SimpleNamespace(
        maker=maker,
        cid=cid,
        advisor=ActorContext(user_id=owner, actor_kind="advisor", actor_id=str(owner)),
        traveler=ActorContext(user_id=traveler, actor_kind="user", actor_id=str(traveler)),
        itin_a=itin_a,
        itin_b=itin_b,
    )
    try:
        yield world
    finally:
        async with maker() as s:
            await s.execute(
                text("delete from public.agent_sessions where client_id = :c"), {"c": cid}
            )
            await s.execute(text("delete from public.itineraries where client_id = :c"), {"c": cid})
            await s.execute(text("delete from public.clients where id = :c"), {"c": cid})
            await s.execute(
                text("delete from auth.users where id = any(:ids)"),
                {"ids": [owner, traveler]},
            )
            await s.commit()
        await engine.dispose()


@integration
async def test_reuse_honors_scope_and_never_re_pins() -> None:
    """Opening trip A then trip B yields two distinct sessions; re-opening A
    reuses A's session and does NOT re-pin it to B (the regression)."""
    async with _world() as w:
        _, s_a, id_a = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        _, s_b, id_b = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_b
        )
        assert s_a is not None and s_b is not None
        assert s_a.id != s_b.id
        assert id_a == w.itin_a and id_b == w.itin_b

        # Re-open scope A → same session, still pinned to A (not re-pinned to B).
        _, s_a2, id_a2 = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert s_a2 is not None and s_a2.id == s_a.id
        assert id_a2 == w.itin_a


@integration
async def test_force_new_opens_distinct_and_reuse_picks_latest() -> None:
    async with _world() as w:
        _, s1, _ = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        _, s2, _ = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a, force_new=True
        )
        assert s1 is not None and s2 is not None and s1.id != s2.id
        # Default reuse now picks the most-recent live session in the scope.
        _, s3, _ = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert s3 is not None and s3.id == s2.id


@integration
async def test_list_is_scope_filtered_and_excludes_archived() -> None:
    async with _world() as w:
        # Two sessions in scope A, one in scope B.
        await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        _, s_a2, _ = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a, force_new=True
        )
        await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_b
        )
        assert s_a2 is not None

        async with w.maker() as s:
            outcome, rows_a = await list_sessions(
                s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
            )
            assert outcome is SessionOutcome.OK and len(rows_a) == 2
            _, rows_b = await list_sessions(
                s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_b
            )
            assert len(rows_b) == 1
            # newest-first ordering
            assert rows_a[0].started_at >= rows_a[1].started_at

            # Archiving one A session drops it from the list.
            await patch_session(s, actor=w.advisor, session_id=s_a2.id, archived=True)
            _, rows_a_after = await list_sessions(
                s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
            )
            assert len(rows_a_after) == 1


@integration
async def test_traveler_cannot_list_advisor_audience() -> None:
    async with _world() as w:
        async with w.maker() as s:
            outcome, rows = await list_sessions(
                s,
                actor=w.traveler,
                client_id=w.cid,
                itinerary_id=w.itin_a,
                audience=SessionAudience.advisor,
            )
        # Collapsed to FORBIDDEN → the router maps it to a 404 existence-hiding shape.
        assert outcome is SessionOutcome.FORBIDDEN
        assert rows == []


@integration
async def test_patch_rename_then_archive_round_trip() -> None:
    async with _world() as w:
        _, sess, _ = await open_or_reuse_session(
            w.maker, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert sess is not None
        async with w.maker() as s:
            outcome, renamed = await patch_session(
                s, actor=w.advisor, session_id=sess.id, title="Tsukiji morning"
            )
            assert outcome is SessionOutcome.OK and renamed is not None
            assert renamed.title == "Tsukiji morning"

            _, archived = await patch_session(s, actor=w.advisor, session_id=sess.id, archived=True)
            assert archived is not None and archived.archived_at is not None

            _, restored = await patch_session(
                s, actor=w.advisor, session_id=sess.id, archived=False
            )
            assert restored is not None and restored.archived_at is None
