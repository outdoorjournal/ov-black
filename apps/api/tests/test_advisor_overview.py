"""Advisor portfolio stats (Wave F) — pure clamp/rollup math + integration.

Pure tests drive :func:`derive_portfolio` with hand-built rows (the money
clamping truth table); ``@integration`` tests seed a two-advisor world in the
local Supabase and assert scoping + the grouped queries. Skip without the DB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services.advisor_overview import derive_portfolio, load_advisor_overview
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _derive(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "client_rows": [],
        "itinerary_rows": [],
        "open_forks": 0,
        "reconcile_requested": 0,
        "invoice_positions": [],
        "session_active": 0,
        "turn_stats": (0, 0, None),
        "now": _NOW,
    }
    defaults.update(overrides)
    return derive_portfolio(**defaults)


# ── pure: bucket totals ──────────────────────────────────────────────────────


def test_client_and_itinerary_buckets_sum_to_total() -> None:
    p = _derive(
        client_rows=[("active", 3), ("pending", 2), ("uninvited", 1)],
        itinerary_rows=[("in_studio", 4), ("with_traveler", 2), ("approved", 1)],
    )
    assert p.clients.total == 6
    assert (p.clients.active, p.clients.pending, p.clients.uninvited) == (3, 2, 1)
    assert p.itineraries.total == 7
    assert (p.itineraries.in_studio, p.itineraries.with_traveler, p.itineraries.approved) == (
        4,
        2,
        1,
    )


def test_empty_roster_is_all_zeroes() -> None:
    p = _derive()
    assert p.clients.total == 0
    assert p.itineraries.total == 0
    assert p.billing == []
    assert p.sessions.active == 0
    assert p.sessions.avg_latency_ms_7d is None


# ── pure: the money clamp truth table ────────────────────────────────────────


def test_outstanding_clamps_per_invoice_not_per_currency() -> None:
    """An over-paid invoice must not hide another invoice's balance."""
    p = _derive(
        invoice_positions=[
            ("USD", Decimal("1000"), Decimal("1200")),  # overpaid → outstanding 0
            ("USD", Decimal("500"), Decimal("0")),  # unpaid → outstanding 500
        ]
    )
    (usd,) = p.billing
    assert usd.invoiced == Decimal("1500")
    assert usd.paid == Decimal("1200")
    # Naive per-currency math would say 300; per-invoice clamping says 500.
    assert usd.outstanding == Decimal("500")


def test_partial_payment_leaves_the_remainder() -> None:
    p = _derive(invoice_positions=[("USD", Decimal("1000"), Decimal("400"))])
    assert p.billing[0].outstanding == Decimal("600")


def test_currencies_do_not_mix() -> None:
    p = _derive(
        invoice_positions=[
            ("EUR", Decimal("800"), Decimal("800")),
            ("USD", Decimal("1000"), Decimal("0")),
        ]
    )
    assert [row.currency for row in p.billing] == ["EUR", "USD"]
    assert p.billing[0].outstanding == Decimal("0")
    assert p.billing[1].outstanding == Decimal("1000")


def test_latency_average_rounds_to_int() -> None:
    p = _derive(turn_stats=(10, 1, 1234.56))
    assert p.sessions.turns_7d == 10
    assert p.sessions.errored_turns_7d == 1
    assert p.sessions.avg_latency_ms_7d == 1235


# ── integration ──────────────────────────────────────────────────────────────


async def _seed_user(s: AsyncSession, uid: uuid.UUID, label: str) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"advf-{label}-{uid}@x.com"},
    )


async def _seed_client(
    s: AsyncSession,
    cid: uuid.UUID,
    owner: uuid.UUID,
    *,
    auth_user: uuid.UUID | None = None,
    invited: bool = False,
) -> None:
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, auth_user_id, full_name, email, "
            "invited_at) values (:id, :o, :a, 'Overview Client', :e, :inv)"
        ),
        {
            "id": cid,
            "o": owner,
            "a": auth_user,
            "e": f"advf-{cid}@x.com",
            "inv": datetime.now(UTC) if invited else None,
        },
    )


async def _seed_invoice_with_lines(
    s: AsyncSession,
    *,
    itinerary_id: uuid.UUID,
    status: str,
    amounts: list[str],
    settled: str | None = None,
) -> uuid.UUID:
    inv = uuid.uuid4()
    await s.execute(
        text(
            "insert into public.invoices (id, itinerary_id, label, status, currency) "
            "values (:id, :iid, 'Deposit', cast(:st as public.invoice_status), 'USD')"
        ),
        {"id": inv, "iid": itinerary_id, "st": status},
    )
    for amount in amounts:
        await s.execute(
            text(
                "insert into public.invoice_line_items (invoice_id, kind, description, "
                "amount, currency) values (:inv, 'charge', 'line', cast(:a as numeric), 'USD')"
            ),
            {"inv": inv, "a": amount},
        )
    if settled is not None:
        await s.execute(
            text(
                "insert into public.payments (invoice_id, amount, currency, status, gateway, "
                "gateway_reference) values (:inv, cast(:a as numeric), 'USD', 'succeeded', "
                "'fake', :ref)"
            ),
            {"inv": inv, "a": settled, "ref": str(uuid.uuid4())},
        )
    await s.commit()
    return inv


async def _seed_session_with_turns(
    s: AsyncSession,
    *,
    client_id: uuid.UUID,
    ended: bool = False,
    turns: int = 0,
    errored: int = 0,
    latency_ms: int | None = None,
    at: datetime | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    await s.execute(
        text(
            "insert into public.agent_sessions (id, client_id, agentcore_session_id, ended_at) "
            "values (:id, :cid, :acs, :ended)"
        ),
        {
            "id": sid,
            "cid": client_id,
            "acs": f"acs-{sid}",
            "ended": datetime.now(UTC) if ended else None,
        },
    )
    created = at or datetime.now(UTC)
    idx = 0
    for _ in range(turns):
        await s.execute(
            text(
                "insert into public.agent_turns (session_id, turn_index, role, content, "
                "actor_kind, latency_ms, created_at) "
                "values (:sid, :idx, 'assistant', 'x', 'agent', :lat, :at)"
            ),
            {"sid": sid, "idx": idx, "lat": latency_ms, "at": created},
        )
        idx += 1
    for _ in range(errored):
        await s.execute(
            text(
                "insert into public.agent_turns (session_id, turn_index, role, content, "
                "actor_kind, error_reason, created_at) "
                "values (:sid, :idx, 'error', '', 'agent', 'boom', :at)"
            ),
            {"sid": sid, "idx": idx, "at": created},
        )
        idx += 1
    await s.commit()
    return sid


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner, traveler, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    c_active, c_pending, c_uninvited, c_stranger = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    async with maker() as s:
        for uid, label in ((owner, "owner"), (traveler, "t"), (stranger, "s")):
            await _seed_user(s, uid, label)
        await _seed_client(s, c_active, owner, auth_user=traveler, invited=True)
        await _seed_client(s, c_pending, owner, invited=True)
        await _seed_client(s, c_uninvited, owner)
        await _seed_client(s, c_stranger, stranger, invited=True)
        await s.commit()

        # Bucketing is derived from nodes now: no approvable nodes → in_studio,
        # a pending approvable node → with_traveler, all actioned → approved.
        i_studio = await insert_itinerary(
            s, title="Studio trip", created_by=owner, client_id=c_active
        )
        i_with = await insert_itinerary(
            s, title="With-traveler trip", created_by=owner, client_id=c_pending
        )
        await insert_node(s, itinerary_id=i_with, type="experience", title="Pending card")
        i_appr = await insert_itinerary(
            s, title="Approved trip", created_by=owner, client_id=c_pending
        )
        await insert_node(
            s, itinerary_id=i_appr, type="experience", title="Approved card", status="approved"
        )
        await insert_itinerary(s, title="Stranger trip", created_by=stranger, client_id=c_stranger)
        # A fork of the studio trip with an open reconcile request.
        fork = await insert_itinerary(s, title="Fork", created_by=owner, client_id=c_active)
        await s.execute(
            text(
                "update public.itineraries set forked_from_id = :base, fork_status = 'open', "
                "reconcile_requested_at = now() where id = :id"
            ),
            {"base": i_studio, "id": fork},
        )
        await s.commit()

        # Money: unpaid issued (500), partially paid issued (1000/400),
        # overpaid paid (1000/1200), plus draft + void that must not count.
        await _seed_invoice_with_lines(s, itinerary_id=i_studio, status="issued", amounts=["500"])
        await _seed_invoice_with_lines(
            s, itinerary_id=i_studio, status="issued", amounts=["600", "400"], settled="400"
        )
        await _seed_invoice_with_lines(
            s, itinerary_id=i_with, status="paid", amounts=["1000"], settled="1200"
        )
        await _seed_invoice_with_lines(s, itinerary_id=i_with, status="draft", amounts=["77"])
        await _seed_invoice_with_lines(s, itinerary_id=i_with, status="void", amounts=["88"])

        # Sessions: one live with turns (2 assistant @1000ms + 1 error), one
        # ended, one stale turn outside the 7-day window, one stranger session.
        await _seed_session_with_turns(s, client_id=c_active, turns=2, errored=1, latency_ms=1000)
        await _seed_session_with_turns(s, client_id=c_pending, ended=True)
        await _seed_session_with_turns(
            s,
            client_id=c_pending,
            turns=5,
            latency_ms=50,
            at=datetime.now(UTC) - timedelta(days=30),
        )
        await _seed_session_with_turns(s, client_id=c_stranger, turns=9, latency_ms=1)

    try:
        yield SimpleNamespace(maker=maker, owner=owner, stranger=stranger)
    finally:
        await engine.dispose()


@integration
async def test_overview_scopes_counts_and_clamps() -> None:
    async with _world() as w, w.maker() as s:
        p = await load_advisor_overview(s, advisor_id=w.owner)

        assert p.clients.total == 3
        assert (p.clients.active, p.clients.pending, p.clients.uninvited) == (1, 1, 1)

        # Trunks only (the fork is excluded from the buckets); stranger's
        # trip invisible.
        assert p.itineraries.total == 3
        assert p.itineraries.in_studio == 1
        assert p.itineraries.with_traveler == 1
        assert p.itineraries.approved == 1
        assert p.itineraries.open_forks == 1
        assert p.itineraries.reconcile_requested == 1

        (usd,) = p.billing
        assert usd.currency == "USD"
        assert usd.invoiced == Decimal("2500")  # 500 + 1000 + 1000; draft/void excluded
        assert usd.paid == Decimal("1600")  # 400 + 1200
        # per-invoice clamp: 500 (unpaid) + 600 (partial) + 0 (overpaid)
        assert usd.outstanding == Decimal("1100")

        # sessions: 3 of the advisor's rows exist, one is ended → 2 active
        # (the stale-turn session is still open, so it counts as active).
        assert p.sessions.active == 2
        # turns: 2 assistant in-window (errors have role='error', stale excluded)
        assert p.sessions.turns_7d == 2
        assert p.sessions.errored_turns_7d == 1
        assert p.sessions.avg_latency_ms_7d == 1000


@integration
async def test_overview_for_the_stranger_sees_only_their_world() -> None:
    async with _world() as w, w.maker() as s:
        p = await load_advisor_overview(s, advisor_id=w.stranger)
        assert p.clients.total == 1
        assert p.itineraries.total == 1
        assert p.billing == []
        assert p.sessions.turns_7d == 9
