"""Advisor awareness feed (ADV-14, Wave D) — the "what wants my attention" rollup.

Two layers, mirroring ``test_messaging.py``:
  - **pure** tests over :func:`app.services.awareness.build_client_attention`
    (the actionable-vs-informational tiering + ordering math — run everywhere);
  - **@integration** tests against the local Supabase that exercise what a fake
    session can't: the four signal queries (reconcile flag, unread with the
    ``last_read_at`` watermark, the JSONB approval detection + window +
    ``actor_kind`` filter, the payment window), advisor scoping isolation, and
    the read-marking round-trip (listing a thread clears its unread). These skip
    when the local DB isn't up (CI has no Postgres).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.agent import ActorContext
from app.services.awareness import (
    AttentionItem,
    build_client_attention,
    classify_urgency,
    load_advisor_attention,
)
from app.services.messaging import list_messages, open_or_create_human_thread, send_message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _item(kind: str, *, at: datetime = _NOW, count: int = 1, urgent: bool = False) -> AttentionItem:
    return AttentionItem(
        kind=kind,  # type: ignore[arg-type]
        itinerary_id=uuid.uuid4(),
        itinerary_title="Trip",
        count=count,
        at=at,
        urgency="urgent" if urgent else "normal",
    )


# ── pure: the tiering + ordering math ────────────────────────────────────────


def test_actionable_signals_light_the_badge_and_sum() -> None:
    cid = uuid.uuid4()
    result = build_client_attention(
        cid,
        [
            _item("changes_requested", count=1),
            _item("unread_messages", count=3),
        ],
    )
    assert result.needs_attention is True
    assert result.attention_count == 4  # 1 reconcile + 3 unread


def test_informational_signals_do_not_light_the_badge() -> None:
    cid = uuid.uuid4()
    result = build_client_attention(
        cid,
        [
            _item("traveler_approved", count=2),
            _item("payment_received", count=1),
        ],
    )
    # Recent-activity kinds are strip context only — the badge stays dark…
    assert result.needs_attention is False
    assert result.attention_count == 0
    # …but they still populate the feed + latest_at for the strip.
    assert len(result.items) == 2
    assert result.latest_at == _NOW


def test_mixed_signals_count_only_actionable_but_feed_carries_all() -> None:
    cid = uuid.uuid4()
    result = build_client_attention(
        cid,
        [
            _item("changes_requested", count=1),
            _item("traveler_approved", count=5),
            _item("payment_received", count=2),
        ],
    )
    assert result.needs_attention is True
    assert result.attention_count == 1  # only the reconcile counts
    assert len(result.items) == 3  # the whole feed is preserved


def test_queue_order_is_actionable_then_urgent_then_newest() -> None:
    """Wave F ordering: an OLD actionable item outranks a NEW informational one,
    and an urgent actionable outranks a newer normal actionable."""
    cid = uuid.uuid4()
    old_urgent = _item("offer_expiring", at=_NOW - timedelta(days=3), urgent=True)
    newer_actionable = _item("changes_requested", at=_NOW)
    newest_info = _item("payment_received", at=_NOW + timedelta(hours=1))
    result = build_client_attention(cid, [newest_info, newer_actionable, old_urgent])
    assert [i.kind for i in result.items] == [
        "offer_expiring",  # urgent actionable first, despite being oldest
        "changes_requested",
        "payment_received",  # informational last, despite being newest
    ]
    # latest_at stays the true max regardless of queue order.
    assert result.latest_at == _NOW + timedelta(hours=1)


def test_new_actionable_kinds_light_the_badge() -> None:
    cid = uuid.uuid4()
    result = build_client_attention(
        cid,
        [
            _item("offer_expiring", urgent=True),
            _item("invoice_unpaid"),
            _item("booking_unconfirmed"),
        ],
    )
    assert result.needs_attention is True
    assert result.attention_count == 3


def test_trip_proposed_is_informational_only() -> None:
    """A proposed trip waits on the traveler — never the advisor's badge."""
    result = build_client_attention(uuid.uuid4(), [_item("trip_proposed")])
    assert result.needs_attention is False
    assert result.attention_count == 0
    assert len(result.items) == 1


def test_full_name_flows_through_the_rollup() -> None:
    result = build_client_attention(uuid.uuid4(), [], full_name="Margaret Chen")
    assert result.full_name == "Margaret Chen"


def test_empty_signals_is_a_dark_badge() -> None:
    result = build_client_attention(uuid.uuid4(), [])
    assert result.needs_attention is False
    assert result.attention_count == 0
    assert result.items == []
    assert result.latest_at is None


# ── pure: the urgency clock ──────────────────────────────────────────────────


def test_offer_expiring_is_always_urgent() -> None:
    assert (
        classify_urgency("offer_expiring", deadline=_NOW + timedelta(hours=23), now=_NOW)
        == "urgent"
    )


def test_invoice_unpaid_turns_urgent_past_due() -> None:
    overdue = classify_urgency("invoice_unpaid", deadline=_NOW - timedelta(days=1), now=_NOW)
    not_due = classify_urgency("invoice_unpaid", deadline=_NOW + timedelta(days=7), now=_NOW)
    undated = classify_urgency("invoice_unpaid", deadline=None, now=_NOW)
    assert overdue == "urgent"
    assert not_due == "normal"
    assert undated == "normal"


def test_other_kinds_are_never_urgent() -> None:
    for kind in ("changes_requested", "unread_messages", "booking_unconfirmed", "trip_proposed"):
        assert classify_urgency(kind, deadline=_NOW - timedelta(days=9), now=_NOW) == "normal"  # type: ignore[arg-type]


# ── integration harness ──────────────────────────────────────────────────────


async def _seed_user(s: AsyncSession, uid: uuid.UUID, label: str) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"adv14-{label}-{uid}@x.com"},
    )


async def _seed_client(
    s: AsyncSession, cid: uuid.UUID, owner: uuid.UUID, traveler: uuid.UUID | None
) -> None:
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
            "values (:id, :o, :a, :n, :e)"
        ),
        {"id": cid, "o": owner, "a": traveler, "n": "ADV14 Client", "e": f"adv14-{cid}@x.com"},
    )


async def _seed_approval(
    s: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    actor_kind: str,
    before_status: str | None,
    after_status: str,
    occurred_at: datetime,
) -> None:
    """One ``node_history`` row (no FK on node_id — a bare uuid is fine)."""
    import json

    await s.execute(
        text(
            """
            insert into public.node_history
              (node_id, itinerary_id, op, actor_kind, before, after, occurred_at)
            values
              (:nid, :iid, 'update', :ak,
               cast(:before as jsonb), cast(:after as jsonb), :at)
            """
        ),
        {
            "nid": uuid.uuid4(),
            "iid": itinerary_id,
            "ak": actor_kind,
            "before": None if before_status is None else json.dumps({"status": before_status}),
            "after": json.dumps({"status": after_status}),
            "at": occurred_at,
        },
    )
    await s.commit()


async def _seed_payment(s: AsyncSession, *, itinerary_id: uuid.UUID, created_at: datetime) -> None:
    # 'paid', matching real settlement (pay_invoice flips issued→paid) — an
    # issued invoice would now honestly light the Wave F invoice_unpaid signal.
    inv = uuid.uuid4()
    await s.execute(
        text(
            "insert into public.invoices (id, itinerary_id, label, status, currency) "
            "values (:id, :iid, 'Balance', 'paid', 'USD')"
        ),
        {"id": inv, "iid": itinerary_id},
    )
    await s.execute(
        text(
            """
            insert into public.payments
              (invoice_id, amount, currency, status, gateway, gateway_reference, created_at)
            values (:inv, 1200.00, 'USD', 'succeeded', 'fake', :ref, :at)
            """
        ),
        {"inv": inv, "ref": str(uuid.uuid4()), "at": created_at},
    )
    await s.commit()


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    """Advisor A owns C1 (reconcile + approval + unread) and C2 (payment +
    excluded approvals); a stranger advisor owns SC (reconcile) for isolation."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner, traveler1, traveler2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stranger = uuid.uuid4()
    c1, c2, sc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    old = _now() - timedelta(days=30)

    async with maker() as s:
        for uid, label in (
            (owner, "owner"),
            (traveler1, "t1"),
            (traveler2, "t2"),
            (stranger, "stranger"),
        ):
            await _seed_user(s, uid, label)
        await _seed_client(s, c1, owner, traveler1)
        await _seed_client(s, c2, owner, traveler2)
        await _seed_client(s, sc, stranger, None)
        await s.commit()
        i1 = await insert_itinerary(s, title="Kyoto", created_by=owner, client_id=c1)
        i2 = await insert_itinerary(s, title="Bali", created_by=owner, client_id=c2)
        si = await insert_itinerary(s, title="Stranger trip", created_by=stranger, client_id=sc)

        # C1: an open reconcile + a genuine traveler approval (in-window).
        await s.execute(
            text("update public.itineraries set reconcile_requested_at = now() where id = :id"),
            {"id": i1},
        )
        await s.commit()
        await _seed_approval(
            s,
            itinerary_id=i1,
            actor_kind="traveler",
            before_status="proposed",
            after_status="approved",
            occurred_at=_now(),
        )

        # C2: a recent payment, plus three approvals that must all be EXCLUDED —
        # an advisor's (wrong actor), an old one (out of window), and a re-save
        # of an already-approved node (not a transition into approved).
        await _seed_payment(s, itinerary_id=i2, created_at=_now())
        await _seed_approval(
            s,
            itinerary_id=i2,
            actor_kind="advisor",
            before_status="proposed",
            after_status="approved",
            occurred_at=_now(),
        )
        await _seed_approval(
            s,
            itinerary_id=i2,
            actor_kind="traveler",
            before_status="proposed",
            after_status="approved",
            occurred_at=old,
        )
        await _seed_approval(
            s,
            itinerary_id=i2,
            actor_kind="traveler",
            before_status="approved",
            after_status="approved",
            occurred_at=_now(),
        )

        # Stranger: an open reconcile that advisor A must never see.
        await s.execute(
            text("update public.itineraries set reconcile_requested_at = now() where id = :id"),
            {"id": si},
        )
        await s.commit()

    try:
        yield SimpleNamespace(
            maker=maker,
            engine=engine,
            owner=owner,
            c1=c1,
            c2=c2,
            sc=sc,
            i1=i1,
            i2=i2,
            advisor=ActorContext(user_id=owner, actor_kind="advisor", actor_id=str(owner)),
            traveler1=ActorContext(user_id=traveler1, actor_kind="user", actor_id=str(traveler1)),
        )
    finally:
        await engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


def _by_client(summaries, cid):  # type: ignore[no-untyped-def]
    for s in summaries:
        if s.client_id == cid:
            return s
    return None


def _kinds(attention):  # type: ignore[no-untyped-def]
    return {i.kind for i in attention.items}


# ── integration: the four signal queries + scoping ───────────────────────────


@integration
async def test_rollup_tiers_signals_and_scopes_to_the_advisor() -> None:
    async with _world() as w, w.maker() as s:
        summaries = await load_advisor_attention(s, advisor_id=w.owner)

        # Only this advisor's clients — the stranger's reconcile is invisible.
        assert {x.client_id for x in summaries} == {w.c1, w.c2}

        c1 = _by_client(summaries, w.c1)
        assert c1 is not None
        assert c1.needs_attention is True  # reconcile is open-state
        assert _kinds(c1) == {"changes_requested", "traveler_approved"}
        # reconcile counts toward the badge; the approval is informational.
        assert c1.attention_count == 1

        c2 = _by_client(summaries, w.c2)
        assert c2 is not None
        # Payment only → informational, dark badge; all three bad approvals dropped.
        assert c2.needs_attention is False
        assert c2.attention_count == 0
        assert _kinds(c2) == {"payment_received"}


@integration
async def test_client_scope_returns_just_that_client() -> None:
    async with _world() as w, w.maker() as s:
        summaries = await load_advisor_attention(s, advisor_id=w.owner, client_id=w.c2)
        assert [x.client_id for x in summaries] == [w.c2]
        assert _kinds(summaries[0]) == {"payment_received"}


# ── integration: unread + the read-marking round-trip ────────────────────────


@integration
async def test_unread_lights_up_then_clears_when_the_advisor_reads() -> None:
    async with _world() as w:
        # The traveler opens the trip thread and posts — unread for the advisor.
        async with w.maker() as s:
            outcome, thread = await open_or_create_human_thread(
                s, actor=w.traveler1, client_id=w.c1, itinerary_id=w.i1
            )
            assert thread is not None
            await send_message(s, actor=w.traveler1, thread_id=thread.id, content="any word?")

        async with w.maker() as s:
            c1 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c1)
            assert c1 is not None
            assert "unread_messages" in _kinds(c1)
            unread_item = next(i for i in c1.items if i.kind == "unread_messages")
            assert unread_item.count == 1
            assert unread_item.itinerary_id == w.i1

        # The advisor opens the thread (lists it) → the read watermark advances.
        async with w.maker() as s:
            await list_messages(s, actor=w.advisor, thread_id=thread.id)

        async with w.maker() as s:
            c1 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c1)
            assert c1 is not None
            assert "unread_messages" not in _kinds(c1)
            # The reconcile is still open, so the badge stays lit for the right reason.
            assert c1.needs_attention is True


# ── integration: the Wave F open-state signals ────────────────────────────────


async def _seed_offer(
    s: AsyncSession,
    *,
    node_id: uuid.UUID,
    expires_at: datetime | None,
    refreshed_from: uuid.UUID | None = None,
) -> uuid.UUID:
    oid = uuid.uuid4()
    await s.execute(
        text(
            """
            insert into public.node_offers
              (id, node_id, source, amount, currency, expires_at, refreshed_from_offer_id)
            values (:id, :nid, 'duffel', 980.00, 'USD', :exp, :prev)
            """
        ),
        {"id": oid, "nid": node_id, "exp": expires_at, "prev": refreshed_from},
    )
    await s.commit()
    return oid


async def _seed_booking(
    s: AsyncSession,
    *,
    node_id: uuid.UUID,
    confirmed_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> uuid.UUID:
    bid = uuid.uuid4()
    await s.execute(
        text(
            """
            insert into public.bookings
              (id, node_id, amount, currency, confirmed_at, cancelled_at)
            values (:id, :nid, 980.00, 'USD', :conf, :canc)
            """
        ),
        {"id": bid, "nid": node_id, "conf": confirmed_at, "canc": cancelled_at},
    )
    await s.commit()
    return bid


async def _seed_invoice(
    s: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    status: str,
    issued_at: datetime | None = None,
    due_at: datetime | None = None,
) -> uuid.UUID:
    iid = uuid.uuid4()
    await s.execute(
        text(
            """
            insert into public.invoices (id, itinerary_id, label, status, currency,
                                         issued_at, due_at)
            values (:id, :iid, 'Deposit', cast(:st as public.invoice_status), 'USD',
                    :issued, :due)
            """
        ),
        {"id": iid, "iid": itinerary_id, "st": status, "issued": issued_at, "due": due_at},
    )
    await s.commit()
    return iid


@integration
async def test_offer_expiring_counts_only_live_unsuperseded_offers() -> None:
    async with _world() as w, w.maker() as s:
        soon = _now() + timedelta(hours=3)
        node = await insert_node(s, itinerary_id=w.i1, type="flight", title="LAX→HND")
        # A superseded offer inside the window must NOT signal…
        stale = await _seed_offer(s, node_id=node, expires_at=soon)
        await _seed_offer(s, node_id=node, expires_at=soon, refreshed_from=stale)
        # …and neither must a no-expiry offer or one far outside the horizon.
        other = await insert_node(s, itinerary_id=w.i1, type="hotel", title="Villa")
        await _seed_offer(s, node_id=other, expires_at=None)
        far = await insert_node(s, itinerary_id=w.i1, type="hotel", title="Ryokan")
        await _seed_offer(s, node_id=far, expires_at=_now() + timedelta(days=9))

        c1 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c1)
        assert c1 is not None
        offers = [i for i in c1.items if i.kind == "offer_expiring"]
        assert len(offers) == 1  # only the live refresh of the flight offer
        assert offers[0].node_id == node
        assert offers[0].urgency == "urgent"
        assert offers[0].deadline is not None
        assert c1.needs_attention is True


@integration
async def test_invoice_unpaid_signals_issued_only_and_overdue_is_urgent() -> None:
    async with _world() as w, w.maker() as s:
        await _seed_invoice(
            s,
            itinerary_id=w.i1,
            status="issued",
            issued_at=_now() - timedelta(days=3),
            due_at=_now() - timedelta(days=1),  # past due → urgent
        )
        # Paid / draft invoices must not signal.
        await _seed_invoice(s, itinerary_id=w.i1, status="paid", issued_at=_now())
        await _seed_invoice(s, itinerary_id=w.i1, status="draft")

        c1 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c1)
        assert c1 is not None
        unpaid = [i for i in c1.items if i.kind == "invoice_unpaid"]
        assert len(unpaid) == 1
        assert unpaid[0].urgency == "urgent"
        # Queue order: the urgent invoice ranks above the normal reconcile.
        actionable_kinds = [i.kind for i in c1.items if i.kind != "traveler_approved"]
        assert actionable_kinds[0] == "invoice_unpaid"


@integration
async def test_booking_unconfirmed_clears_on_confirm_or_cancel() -> None:
    async with _world() as w, w.maker() as s:
        pending = await insert_node(s, itinerary_id=w.i2, type="hotel", title="Aman")
        confirmed = await insert_node(s, itinerary_id=w.i2, type="hotel", title="Ritz")
        cancelled = await insert_node(s, itinerary_id=w.i2, type="hotel", title="Four S")
        await _seed_booking(s, node_id=pending)
        await _seed_booking(s, node_id=confirmed, confirmed_at=_now())
        await _seed_booking(s, node_id=cancelled, cancelled_at=_now())

        c2 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c2)
        assert c2 is not None
        unconfirmed = [i for i in c2.items if i.kind == "booking_unconfirmed"]
        assert [i.node_id for i in unconfirmed] == [pending]
        assert c2.needs_attention is True


@integration
async def test_trip_proposed_windows_and_stays_informational() -> None:
    async with _world() as w, w.maker() as s:
        await s.execute(
            text(
                "update public.itineraries set status = 'proposed', proposed_at = :at "
                "where id = :id"
            ),
            {"id": w.i2, "at": _now() - timedelta(days=2)},
        )
        await s.commit()

        c2 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c2)
        assert c2 is not None
        assert "trip_proposed" in _kinds(c2)
        # Proposed waits on the traveler — informational, so no badge from it.
        assert all(i.kind != "trip_proposed" or i.count == 1 for i in c2.items)
        assert c2.needs_attention is False

        # Out-of-window proposals drop off the strip.
        await s.execute(
            text("update public.itineraries set proposed_at = :at where id = :id"),
            {"id": w.i2, "at": _now() - timedelta(days=40)},
        )
        await s.commit()
        c2 = _by_client(await load_advisor_attention(s, advisor_id=w.owner), w.c2)
        assert c2 is None or "trip_proposed" not in _kinds(c2)


@integration
async def test_full_name_rides_the_rollup() -> None:
    async with _world() as w, w.maker() as s:
        summaries = await load_advisor_attention(s, advisor_id=w.owner)
        assert all(x.full_name == "ADV14 Client" for x in summaries)
