"""M006/PS7 — the human messaging channel (threads + messages, no agent turn).

Two layers:
  - a plain unit test for the author-kind mapping (runs everywhere);
  - ``@integration`` tests against the local Supabase (127.0.0.1:54322) that
    exercise the real query behaviour a fake session can't model: get-or-create
    per scope, the send/list round-trip, participant seeding, the "no agent
    turn" invariant, the cross-tenant access gate, and the 0037 RLS policies
    (a participant sees the thread; a non-member is blind). These skip when the
    local DB isn't up (CI has no Postgres), mirroring the other integration
    suites.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.models import SessionAudience, ThreadActorKind
from app.services.agent import ActorContext
from app.services.messaging import (
    MessagingOutcome,
    _author_kind_for,
    list_messages,
    open_or_create_human_thread,
    send_message,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── unit: author-kind mapping ───────────────────────────────────────────────


def test_author_kind_maps_principal_to_human_kind() -> None:
    advisor = ActorContext(user_id=uuid.uuid4(), actor_kind="advisor", actor_id="a")
    traveler = ActorContext(user_id=uuid.uuid4(), actor_kind="user", actor_id="t")
    assert _author_kind_for(advisor) is ThreadActorKind.advisor
    assert _author_kind_for(traveler) is ThreadActorKind.traveler


# ── integration harness ──────────────────────────────────────────────────────


async def _seed_user(s: AsyncSession, uid: uuid.UUID, label: str) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"ps7-{label}-{uid}@x.com"},
    )


async def _seed_client(
    s: AsyncSession, cid: uuid.UUID, owner: uuid.UUID, traveler: uuid.UUID
) -> None:
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
            "values (:id, :o, :a, :n, :e)"
        ),
        {"id": cid, "o": owner, "a": traveler, "n": "PS7 Client", "e": f"ps7-{cid}@x.com"},
    )


@asynccontextmanager
async def _world() -> AsyncIterator[SimpleNamespace]:
    """A seeded client (advisor owner + traveler auth link), two itineraries, and
    an unrelated stranger client for the cross-tenant gate."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    cid, owner, traveler = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stranger_cid, stranger_owner, stranger_traveler = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    async with maker() as s:
        for uid, label in (
            (owner, "owner"),
            (traveler, "traveler"),
            (stranger_owner, "s-owner"),
            (stranger_traveler, "s-traveler"),
        ):
            await _seed_user(s, uid, label)
        await _seed_client(s, cid, owner, traveler)
        await _seed_client(s, stranger_cid, stranger_owner, stranger_traveler)
        await s.commit()
        itin_a = await insert_itinerary(s, title="Trip A", created_by=owner, client_id=cid)
        itin_b = await insert_itinerary(s, title="Trip B", created_by=owner, client_id=cid)
        await s.commit()
    try:
        yield SimpleNamespace(
            maker=maker,
            engine=engine,
            cid=cid,
            owner=owner,
            traveler_uid=traveler,
            advisor=ActorContext(user_id=owner, actor_kind="advisor", actor_id=str(owner)),
            traveler=ActorContext(user_id=traveler, actor_kind="user", actor_id=str(traveler)),
            stranger_advisor=ActorContext(
                user_id=stranger_owner, actor_kind="advisor", actor_id=str(stranger_owner)
            ),
            stranger_traveler=ActorContext(
                user_id=stranger_traveler,
                actor_kind="user",
                actor_id=str(stranger_traveler),
            ),
            itin_a=itin_a,
            itin_b=itin_b,
        )
    finally:
        await engine.dispose()


# ── get-or-create per scope ──────────────────────────────────────────────────


@integration
async def test_get_or_create_is_idempotent_per_scope() -> None:
    async with _world() as w, w.maker() as s:
        ok1, t1 = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        ok2, t2 = await open_or_create_human_thread(
            s, actor=w.traveler, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert ok1 is MessagingOutcome.OK and ok2 is MessagingOutcome.OK
        assert t1 is not None and t2 is not None
        # Same scope → the SAME thread (advisor and traveler share one channel).
        assert t1.id == t2.id
        assert t1.audience is SessionAudience.traveler

        # A different itinerary is a different thread; basecamp (None) is another.
        _, t_b = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_b
        )
        _, t_base = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=None
        )
        assert t_b is not None and t_base is not None
        assert len({t1.id, t_b.id, t_base.id}) == 3


# ── send / list round-trip + no-agent-turn invariant ─────────────────────────


@integration
async def test_send_and_list_roundtrip_no_agent_turn() -> None:
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert thread is not None

        _, m_adv = await send_message(
            s, actor=w.advisor, thread_id=thread.id, content="Welcome — I'm your advisor."
        )
        _, m_trav = await send_message(
            s, actor=w.traveler, thread_id=thread.id, content="Thanks! Excited for this."
        )
        assert m_adv is not None and m_trav is not None
        assert m_adv.author_kind is ThreadActorKind.advisor
        assert m_adv.author_id == w.owner
        assert m_trav.author_kind is ThreadActorKind.traveler
        assert m_trav.author_id == w.traveler_uid

        ok, rows = await list_messages(s, actor=w.traveler, thread_id=thread.id)
        assert ok is MessagingOutcome.OK
        assert [m.content for m in rows] == [
            "Welcome — I'm your advisor.",
            "Thanks! Excited for this.",
        ]

        # The human channel opens NO agent session and writes NO agent turn.
        n_sessions = (
            await s.execute(
                text("select count(*) from public.agent_sessions where client_id = :c"),
                {"c": w.cid},
            )
        ).scalar_one()
        assert n_sessions == 0


# ── participant seeding ──────────────────────────────────────────────────────


@integration
async def test_open_seeds_traveler_and_advisor_participants() -> None:
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert thread is not None
        rows = (
            await s.execute(
                text(
                    "select actor_id, actor_kind from public.thread_participants "
                    "where thread_id = :t order by actor_kind"
                ),
                {"t": thread.id},
            )
        ).all()
        by_kind = {kind: actor_id for actor_id, kind in rows}
        assert by_kind.get("advisor") == w.owner
        assert by_kind.get("traveler") == w.traveler_uid


# ── cross-tenant access gate ─────────────────────────────────────────────────


@integration
async def test_stranger_cannot_open_send_or_list() -> None:
    async with _world() as w, w.maker() as s:
        # Seed a real thread + message via the legitimate advisor.
        _, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert thread is not None
        await send_message(s, actor=w.advisor, thread_id=thread.id, content="private")

        # A stranger advisor / traveler is FORBIDDEN everywhere (collapses to 404).
        for stranger in (w.stranger_advisor, w.stranger_traveler):
            oc_open, _ = await open_or_create_human_thread(
                s, actor=stranger, client_id=w.cid, itinerary_id=w.itin_a
            )
            assert oc_open is MessagingOutcome.FORBIDDEN
            oc_list, rows = await list_messages(s, actor=stranger, thread_id=thread.id)
            assert oc_list is MessagingOutcome.FORBIDDEN and rows == []
            oc_send, msg = await send_message(
                s, actor=stranger, thread_id=thread.id, content="I should not get in"
            )
            assert oc_send is MessagingOutcome.FORBIDDEN and msg is None


@integration
async def test_foreign_itinerary_is_hidden() -> None:
    async with _world() as w, w.maker() as s:
        # Give the stranger client its own itinerary, then try to scope OUR
        # thread to it: the itinerary-ownership check must reject (→ FORBIDDEN).
        foreign_itin = await insert_itinerary(
            s, title="Foreign", created_by=w.stranger_advisor.user_id
        )
        await s.execute(
            text("update public.itineraries set client_id = null where id = :i"),
            {"i": foreign_itin},
        )
        await s.commit()
        oc, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=foreign_itin
        )
        assert oc is MessagingOutcome.FORBIDDEN and thread is None


# ── 0037 RLS policies (defense-in-depth) ─────────────────────────────────────


@integration
async def test_rls_participant_sees_thread_nonmember_blind() -> None:
    """The API bypasses RLS (owner role), so verify the policies directly: a
    participant/owner sees the thread; an unrelated authenticated user is blind."""
    async with _world() as w:
        async with w.maker() as s:
            _, thread = await open_or_create_human_thread(
                s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
            )
            assert thread is not None
            tid = thread.id

        async def _visible_as(uid: uuid.UUID) -> int:
            # A fresh connection so SET LOCAL ROLE / claims are isolated.
            async with w.engine.connect() as conn:
                await conn.execute(text("set local role authenticated"))
                await conn.execute(
                    text("select set_config('request.jwt.claims', :c, true)"),
                    {"c": f'{{"sub":"{uid}"}}'},
                )
                return (
                    await conn.execute(
                        text("select count(*) from public.threads where id = :t"),
                        {"t": tid},
                    )
                ).scalar_one()

        assert await _visible_as(w.owner) == 1  # advisor owner sees it
        assert await _visible_as(w.traveler_uid) == 1  # participant traveler sees it
        assert await _visible_as(uuid.uuid4()) == 0  # a non-member is blind
        assert await _visible_as(w.stranger_traveler.user_id) == 0  # stranger blind


# ── AGT-4: the agent's escalation write ──────────────────────────────────────


@integration
async def test_agent_escalation_posts_artemis_message_creating_thread() -> None:
    """post_agent_thread_message get-or-creates the scope thread and posts one
    author_kind='artemis' message with no human author id."""
    from app.services.messaging import post_agent_thread_message

    async with _world() as w, w.maker() as s:
        outcome, message = await post_agent_thread_message(
            s,
            client_id=w.cid,
            itinerary_id=w.itin_a,
            content="Client asks about a private chef evening in Kyoto.",
        )
        assert outcome is MessagingOutcome.OK and message is not None
        assert message.author_kind is ThreadActorKind.artemis
        assert message.author_id is None

        # The same scope resolves to the SAME thread the humans use — the
        # advisor opening it afterwards sees the escalation.
        ok, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin_a
        )
        assert ok is MessagingOutcome.OK and thread is not None
        assert thread.id == message.thread_id
        _, rows = await list_messages(s, actor=w.advisor, thread_id=thread.id)
        assert [m.id for m in rows] == [message.id]


@integration
async def test_agent_escalation_refuses_foreign_itinerary() -> None:
    """A mis-pinned session cannot post into another client's trip thread."""
    from app.services.messaging import post_agent_thread_message

    async with _world() as w, w.maker() as s:
        foreign_itin = await insert_itinerary(
            s, title="Foreign", created_by=w.stranger_advisor.user_id, client_id=None
        )
        await s.commit()
        outcome, message = await post_agent_thread_message(
            s, client_id=w.cid, itinerary_id=foreign_itin, content="x"
        )
        assert outcome is MessagingOutcome.FORBIDDEN and message is None
