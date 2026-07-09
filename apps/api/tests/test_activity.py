"""The merged advisor activity feed (Wave F) — pure ordering/cursor math +
integration over the per-source queries.

The load-bearing integration case is the cursor walk: pages must neither skip
nor duplicate events across a boundary, including the same-timestamp tie
resolved by ``(kind ASC, source_id ASC)`` — the SQL predicates and the Python
merge must agree on that order or pagination silently corrupts.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.activity import (
    ActivityEvent,
    load_advisor_activity,
    next_cursor_for,
    sort_key_desc,
)
from app.services.agent import ActorContext
from app.services.messaging import open_or_create_human_thread, send_message
from app.services.pagination import decode_cursor
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _event(kind: str, *, at: datetime = _NOW, source_id: str = "1") -> ActivityEvent:
    return ActivityEvent(
        kind=kind,  # type: ignore[arg-type]
        at=at,
        source_id=source_id,
        client_id=uuid.uuid4(),
        itinerary_id=None,
        itinerary_title=None,
        actor_kind=None,
        title=None,
        op=None,
        status_before=None,
        status_after=None,
        amount=None,
        currency=None,
        ref_id=None,
    )


# ── pure ─────────────────────────────────────────────────────────────────────


def test_sort_is_newest_first_with_kind_then_id_ties() -> None:
    older = _event("payment", at=_NOW - timedelta(minutes=5))
    tie_a = _event("agent_turn", at=_NOW, source_id="9")
    tie_b = _event("node_changed", at=_NOW, source_id="1")
    tie_a2 = _event("agent_turn", at=_NOW, source_id="10")
    ordered = sorted([older, tie_a, tie_b, tie_a2], key=sort_key_desc)
    # Same instant: kind ASC (agent_turn < node_changed), then source_id ASC
    # (lexicographic: "10" < "9" — matching the SQL text cast).
    assert [(e.kind, e.source_id) for e in ordered] == [
        ("agent_turn", "10"),
        ("agent_turn", "9"),
        ("node_changed", "1"),
        ("payment", "1"),
    ]


def test_next_cursor_only_on_a_full_page_and_round_trips() -> None:
    events = [_event("payment", source_id=str(i)) for i in range(3)]
    assert next_cursor_for(events, limit=5) is None  # short page = the end
    token = next_cursor_for(events, limit=3)
    assert token is not None
    payload = decode_cursor(token)
    assert payload == {"at": _NOW.isoformat(), "kind": "payment", "source_id": "2"}


def test_event_shape_carries_no_content_field() -> None:
    """Redaction is structural: the projection has no slot for message/turn text."""
    fields = {f.name for f in dataclasses.fields(ActivityEvent)}
    assert "content" not in fields
    assert "text" not in fields
    assert "before" not in fields and "after" not in fields


# ── integration ──────────────────────────────────────────────────────────────


async def _seed_user(s: AsyncSession, uid: uuid.UUID, label: str) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"act-{label}-{uid}@x.com"},
    )


async def _seed_client(s: AsyncSession, cid: uuid.UUID, owner: uuid.UUID) -> None:
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, full_name, email) "
            "values (:id, :o, 'Activity Client', :e)"
        ),
        {"id": cid, "o": owner, "e": f"act-{cid}@x.com"},
    )


async def _seed_history(
    s: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    occurred_at: datetime,
    title: str = "Card",
    status_after: str = "proposed",
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
            "b": '{"status": "idea"}',
            "a": f'{{"status": "{status_after}", "title": "{title}"}}',
            "at": occurred_at,
        },
    )
    await s.commit()


async def _seed_paid_invoice(
    s: AsyncSession, *, itinerary_id: uuid.UUID, at: datetime
) -> uuid.UUID:
    inv = uuid.uuid4()
    await s.execute(
        text(
            "insert into public.invoices (id, itinerary_id, label, status, currency, "
            "issued_at, created_at) "
            "values (:id, :iid, 'Deposit', 'paid', 'USD', :at, :at)"
        ),
        {"id": inv, "iid": itinerary_id, "at": at},
    )
    await s.execute(
        text(
            "insert into public.payments (invoice_id, amount, currency, status, gateway, "
            "gateway_reference, created_at) "
            "values (:inv, 750.00, 'USD', 'succeeded', 'fake', :ref, :at)"
        ),
        {"inv": inv, "ref": str(uuid.uuid4()), "at": at},
    )
    await s.commit()
    return inv


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner, traveler, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cid, sc = uuid.uuid4(), uuid.uuid4()
    async with maker() as s:
        for uid, label in ((owner, "owner"), (traveler, "t"), (stranger, "s")):
            await _seed_user(s, uid, label)
        await _seed_client(s, cid, owner)
        await _seed_client(s, sc, stranger)
        await s.commit()
        itin = await insert_itinerary(s, title="Kyoto", created_by=owner, client_id=cid)
        s_itin = await insert_itinerary(s, title="Elsewhere", created_by=stranger, client_id=sc)

        # Graph beats at t0-3m, t0-2m; a same-instant PAIR at t0 (history +
        # payment) to exercise the cross-source tie; stranger noise throughout.
        await _seed_history(s, itinerary_id=itin, occurred_at=_now() - timedelta(minutes=3))
        await _seed_history(s, itinerary_id=itin, occurred_at=_now() - timedelta(minutes=2))
        tie_at = _now()
        await _seed_history(s, itinerary_id=itin, occurred_at=tie_at, title="Tie card")
        await _seed_paid_invoice(s, itinerary_id=itin, at=tie_at)
        await _seed_history(s, itinerary_id=s_itin, occurred_at=_now())

        # One human message from the traveler (needs a participant-linked actor).
        actor = ActorContext(user_id=owner, actor_kind="advisor", actor_id=str(owner))
        _, thread = await open_or_create_human_thread(
            s, actor=actor, client_id=cid, itinerary_id=itin
        )
        assert thread is not None
        await send_message(s, actor=actor, thread_id=thread.id, content="SECRET-CONTENT")

    try:
        yield SimpleNamespace(maker=maker, owner=owner, stranger=stranger, cid=cid, itin=itin)
    finally:
        await engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


@integration
async def test_feed_merges_sources_scoped_to_the_advisor() -> None:
    async with _world() as w, w.maker() as s:
        events = await load_advisor_activity(s, advisor_id=w.owner, limit=50)
        kinds = {e.kind for e in events}
        # history ×3, invoice_created + invoice_issued + payment, message ×1.
        assert kinds == {
            "node_changed",
            "invoice_created",
            "invoice_issued",
            "payment",
            "message_posted",
        }
        # The stranger's graph beat is invisible.
        assert all(e.client_id == w.cid for e in events)
        # Redaction: nothing carries the message body.
        assert all(
            "SECRET-CONTENT" not in (e.title or "") and "SECRET-CONTENT" not in (e.op or "")
            for e in events
        )


@integration
async def test_cursor_walk_never_skips_nor_duplicates() -> None:
    async with _world() as w, w.maker() as s:
        full = await load_advisor_activity(s, advisor_id=w.owner, limit=50)
        assert len(full) >= 6

        walked: list[tuple[str, str]] = []
        cursor: dict[str, object] | None = None
        for _ in range(10):
            page = await load_advisor_activity(s, advisor_id=w.owner, limit=2, cursor=cursor)
            walked.extend((e.kind, e.source_id) for e in page)
            if len(page) < 2:
                break
            token = next_cursor_for(page, 2)
            assert token is not None
            cursor = decode_cursor(token)

        assert walked == [(e.kind, e.source_id) for e in full]
        assert len(walked) == len(set(walked))


@integration
async def test_kinds_filter_skips_sources() -> None:
    async with _world() as w, w.maker() as s:
        events = await load_advisor_activity(
            s, advisor_id=w.owner, limit=50, kinds=frozenset({"payment"})
        )
        assert [e.kind for e in events] == ["payment"]
        assert events[0].amount is not None


@integration
async def test_after_mode_returns_only_newer_ascending() -> None:
    async with _world() as w, w.maker() as s:
        watermark = _now() - timedelta(minutes=2, seconds=30)
        events = await load_advisor_activity(s, advisor_id=w.owner, limit=50, after=watermark)
        assert events, "expected events newer than the watermark"
        assert all(e.at > watermark for e in events)
        assert [e.at for e in events] == sorted(e.at for e in events)


@integration
async def test_foreign_client_scope_is_the_empty_feed() -> None:
    async with _world() as w, w.maker() as s:
        events = await load_advisor_activity(s, advisor_id=w.stranger, limit=50, client_id=w.cid)
        assert events == []
