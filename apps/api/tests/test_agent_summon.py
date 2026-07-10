"""M006/PS8 — the Artemis-in-human-chat bridge (@-mention).

A human posts an ``@Artemis`` message into a human thread; the bridge runs one
thread-scoped agent turn and inserts a single ``author_kind='artemis'`` message.

Two layers:
  - plain unit tests for the mention parse (``mentions_artemis`` / ``strip_mention``),
    which run everywhere;
  - ``@integration`` tests against local Supabase (127.0.0.1:54322) that exercise
    the real turn: the reply lands as an ``artemis`` message, the **disclosure
    invariant** (the bridge takes no summoner — an advisor-typed mention is as
    client-safe as a traveler's), a **proposal lands on the single graph**, and
    the **redaction sweep** (Dossier/OSINT/net-worth never leak into a log
    record). These skip when the DB isn't up (CI has no Postgres).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from app.agent.bedrock import MockAgentRuntimeClient
from app.config import Settings
from app.services.agent import (
    ActorContext,
    mentions_artemis,
    strip_mention,
    summon_artemis_in_thread,
)
from app.services.messaging import open_or_create_human_thread, send_message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

# ── unit: mention parse ──────────────────────────────────────────────────────


def test_mentions_artemis_matches_standalone_token() -> None:
    assert mentions_artemis("@Artemis what do you think?")
    assert mentions_artemis("Hey @artemis, help us pick")
    assert mentions_artemis("...and @ARTEMIS please")
    # Not a mention: glued to a word (an email-ish address).
    assert not mentions_artemis("mail me at chris@artemis.example")
    assert not mentions_artemis("just talking about artemis the goddess")
    assert not mentions_artemis("no mention here at all")


def test_strip_mention_removes_token_and_collapses_space() -> None:
    assert strip_mention("@Artemis suggest a dinner") == "suggest a dinner"
    assert strip_mention("Hey @artemis, help") == "Hey , help"
    # A bare mention falls back to a neutral opener so the turn still has input.
    assert strip_mention("@Artemis") == "Hello — how can you help with this trip?"


# ── integration harness ──────────────────────────────────────────────────────


async def _seed_user(s: AsyncSession, uid: uuid.UUID, label: str) -> None:
    await s.execute(
        text(
            "insert into auth.users (id, email, aud, role, instance_id) "
            "values (:id, :email, 'authenticated', 'authenticated', "
            "'00000000-0000-0000-0000-000000000000')"
        ),
        {"id": uid, "email": f"ps8-{label}-{uid}@x.com"},
    )


async def _seed_client(
    s: AsyncSession, cid: uuid.UUID, owner: uuid.UUID, traveler: uuid.UUID
) -> None:
    await s.execute(
        text(
            "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
            "values (:id, :o, :a, :n, :e)"
        ),
        {"id": cid, "o": owner, "a": traveler, "n": "PS8 Client", "e": f"ps8-{cid}@x.com"},
    )


async def _seed_dossier(
    s: AsyncSession, cid: uuid.UUID, owner: uuid.UUID, *, net_worth: int
) -> None:
    await s.execute(
        text(
            "insert into public.dossiers "
            "  (client_id, authored_by, contact_preference, "
            "   travel_party_notes, estimated_net_worth_usd) "
            "values (:c, :a, 'email', :notes, :nw)"
        ),
        {"c": cid, "a": owner, "notes": "party_note_sentinel", "nw": net_worth},
    )


async def _seed_fact(
    s: AsyncSession, table: str, cid: uuid.UUID, owner: uuid.UUID, *, kind: str, body: str
) -> None:
    await s.execute(
        text(
            f"insert into public.{table} (client_id, kind, text, source_kind, recorded_by) "
            f"values (:c, cast(:k as public.{table[:-1]}_kind), :t, 'advisor', :r)"
        ),
        {"c": cid, "k": kind, "t": body, "r": owner},
    )


@asynccontextmanager
async def _world(*, net_worth: int = 250_000_000) -> AsyncIterator[SimpleNamespace]:
    """A seeded client (advisor owner + traveler auth link) with a dossier +
    sensitive facts, and one itinerary the human thread is scoped to."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    cid, owner, traveler = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with maker() as s:
        await _seed_user(s, owner, "owner")
        await _seed_user(s, traveler, "traveler")
        await _seed_client(s, cid, owner, traveler)
        await _seed_dossier(s, cid, owner, net_worth=net_worth)
        await _seed_fact(
            s, "dossier_facts", cid, owner, kind="passion", body="loves_heli_skiing_sentinel"
        )
        await _seed_fact(s, "osint_facts", cid, owner, kind="linkedin", body="cfo_at_acme_sentinel")
        await s.commit()
        itin = await insert_itinerary(s, title="Trip A", created_by=owner, client_id=cid)
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
            itin=itin,
        )
    finally:
        await engine.dispose()


def _delta(text_chunk: str) -> dict[str, Any]:
    return {"type": "delta", "text": text_chunk}


_DONE: dict[str, Any] = {"type": "done"}


# ── the reply lands as an artemis message ────────────────────────────────────


@integration
async def test_summon_inserts_artemis_message(settings_override: Settings) -> None:
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin
        )
        assert thread is not None
        _, trigger = await send_message(
            s, actor=w.traveler, thread_id=thread.id, content="@Artemis suggest a dinner"
        )
        assert trigger is not None

        runtime = MockAgentRuntimeClient(
            [_delta("A quiet kaiseki would suit "), _delta("the evening."), _DONE]
        )
        msg_id = await summon_artemis_in_thread(
            w.maker,
            runtime,
            thread_id=thread.id,
            trigger_content="@Artemis suggest a dinner",
            trigger_message_id=trigger.id,
            settings=settings_override,
        )
        assert msg_id is not None

        row = (
            await s.execute(
                text("select author_kind, author_id, content from public.messages where id = :m"),
                {"m": msg_id},
            )
        ).one()
        author_kind, author_id, content = row
        assert author_kind == "artemis"
        assert author_id is None  # Artemis has no auth.users identity.
        assert content == "A quiet kaiseki would suit the evening."

        # An engine session was bound to the thread (Q13=UNIFY forward hook), and
        # no human-visible agent_turns were written (the thread messages ARE the log).
        engine_row = (
            await s.execute(
                text(
                    "select count(*) from public.agent_sessions "
                    "where thread_id = :t and client_id = :c"
                ),
                {"t": thread.id, "c": w.cid},
            )
        ).scalar_one()
        assert engine_row == 1


# ── disclosure follows the THREAD, not the summoner ──────────────────────────


@integration
async def test_summon_disclosure_follows_thread_not_summoner(
    settings_override: Settings,
) -> None:
    """The bridge takes NO summoner principal, so an advisor-typed mention gets the
    exact same client-safe framing a traveler's would. We assert the runtime
    payload is client-facing (audience=traveler, actor_kind=user, no bearer) and
    that the two summons (advisor-authored vs traveler-authored trigger) send an
    identical system prompt + disclosure framing."""
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.advisor, client_id=w.cid, itinerary_id=w.itin
        )
        assert thread is not None

        async def _summon_as(actor: ActorContext) -> dict[str, Any]:
            _, trig = await send_message(
                s, actor=actor, thread_id=thread.id, content="@Artemis what fits?"
            )
            assert trig is not None
            runtime = MockAgentRuntimeClient([_delta("Something quiet."), _DONE])
            await summon_artemis_in_thread(
                w.maker,
                runtime,
                thread_id=thread.id,
                trigger_content="@Artemis what fits?",
                trigger_message_id=trig.id,
                settings=settings_override,
            )
            return dict(runtime.calls[0]["payload"])

        advisor_payload = await _summon_as(w.advisor)
        traveler_payload = await _summon_as(w.traveler)

        for payload in (advisor_payload, traveler_payload):
            # Client-facing framing regardless of who summoned.
            assert payload["audience"] == "traveler"
            assert payload["actor_kind"] == "user"
            assert payload["auth_bearer"] == ""
            # The disclosure rubric is in the system prompt every turn.
            assert "Disclosure rules" in payload["system"]
            assert "OSINT facts: NEVER" in payload["system"]

        # The summoner cannot shift disclosure: identical system prompt + audience.
        assert advisor_payload["system"] == traveler_payload["system"]
        assert advisor_payload["audience"] == traveler_payload["audience"]
        assert advisor_payload["actor_kind"] == traveler_payload["actor_kind"]


# ── a proposal lands on the single graph ─────────────────────────────────────


@integration
async def test_summon_proposal_lands_on_graph(settings_override: Settings) -> None:
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.traveler, client_id=w.cid, itinerary_id=w.itin
        )
        assert thread is not None
        _, trigger = await send_message(
            s, actor=w.traveler, thread_id=thread.id, content="@Artemis add a dinner"
        )
        assert trigger is not None

        card = {
            "type": "card",
            "source": "ov",
            "source_id": "exp-kaiseki-1",
            "snapshot": {"title": "Kaiseki dinner"},
        }
        runtime = MockAgentRuntimeClient([_delta("Here's one to consider."), card, _DONE])
        msg_id = await summon_artemis_in_thread(
            w.maker,
            runtime,
            thread_id=thread.id,
            trigger_content="@Artemis add a dinner",
            trigger_message_id=trigger.id,
            settings=settings_override,
        )
        assert msg_id is not None

        # Cards never land on the official trunk — the bridge resolves (and
        # lazily creates) the traveler's working fork of the thread's itinerary.
        fork_row = (
            await s.execute(
                text(
                    "select id, created_by, fork_status from public.itineraries "
                    "where forked_from_id = :i"
                ),
                {"i": w.itin},
            )
        ).one()
        fork_id, fork_created_by, fork_status = fork_row
        assert fork_created_by == w.traveler_uid  # the session client's own fork
        assert fork_status == "open"

        # The pending-experience node landed in the fork…
        node_row = (
            await s.execute(
                text(
                    "select id, type, status from public.nodes "
                    "where itinerary_id = :i and source_id = 'exp-kaiseki-1'"
                ),
                {"i": fork_id},
            )
        ).one()
        node_id, node_type, node_status = node_row
        assert node_type == "experience"
        assert node_status == "pending"

        # …and the trunk stayed clean.
        trunk_nodes = (
            await s.execute(
                text("select count(*) from public.nodes where itinerary_id = :i"),
                {"i": w.itin},
            )
        ).scalar_one()
        assert trunk_nodes == 0

        # …and the Artemis message points at it (proposed_node_id on the spine).
        proposed = (
            await s.execute(
                text("select proposed_node_id from public.messages where id = :m"),
                {"m": msg_id},
            )
        ).scalar_one()
        assert proposed == node_id


# ── redaction: no sensitive substring leaks into a log record ────────────────

_SENTINELS = [
    "250000000",  # net worth as rendered
    "party_note_sentinel",
    "loves_heli_skiing_sentinel",
    "cfo_at_acme_sentinel",
]


@integration
async def test_summon_no_sensitive_substring_leaks_into_logs(
    settings_override: Settings,
    caplog: Any,
) -> None:
    caplog.set_level(logging.DEBUG)
    async with _world() as w, w.maker() as s:
        _, thread = await open_or_create_human_thread(
            s, actor=w.traveler, client_id=w.cid, itinerary_id=w.itin
        )
        assert thread is not None
        _, trigger = await send_message(
            s, actor=w.traveler, thread_id=thread.id, content="@Artemis ideas?"
        )
        assert trigger is not None

        runtime = MockAgentRuntimeClient([_delta("A calm evening plan."), _DONE])
        msg_id = await summon_artemis_in_thread(
            w.maker,
            runtime,
            thread_id=thread.id,
            trigger_content="@Artemis ideas?",
            trigger_message_id=trigger.id,
            settings=settings_override,
        )
        assert msg_id is not None

    # The dossier/OSINT/net-worth signals reached the model (they're in the
    # system prompt) but must appear in NO log record.
    system_prompt = str(runtime.calls[0]["payload"]["system"])
    assert "loves_heli_skiing_sentinel" in system_prompt  # sanity: sweep is meaningful
    for rec in caplog.records:
        blob = rec.getMessage() + " " + str(rec.__dict__)
        for sentinel in _SENTINELS:
            assert sentinel not in blob, f"{sentinel!r} leaked into {rec.name} {rec.levelname}"


# ── ai_session threads don't summon here ─────────────────────────────────────


@integration
async def test_summon_ignores_non_human_thread(settings_override: Settings) -> None:
    async with _world() as w, w.maker() as s:
        ai_thread_id = uuid.uuid4()
        await s.execute(
            text(
                "insert into public.threads (id, client_id, itinerary_id, kind, audience) "
                "values (:id, :c, :i, 'ai_session', 'traveler')"
            ),
            {"id": ai_thread_id, "c": w.cid, "i": w.itin},
        )
        await s.commit()

        runtime = MockAgentRuntimeClient([_delta("should not run"), _DONE])
        msg_id = await summon_artemis_in_thread(
            w.maker,
            runtime,
            thread_id=ai_thread_id,
            trigger_content="@Artemis hi",
            settings=settings_override,
        )
        assert msg_id is None
        assert runtime.calls == []  # the runtime was never invoked
