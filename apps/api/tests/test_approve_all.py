"""Approve-all (0044) — the per-node bulk approval that replaced the
itinerary-level approve.

Two layers:

1. Service tests over :func:`app.services.itineraries.approve_all_nodes`
   against the local Supabase: 404 on a missing itinerary, 409 ``not_a_trunk``
   on a fork, the approvability scoping (annotation kinds / discarded /
   deselected alternatives untouched), the one-history-row-per-node audit
   contract, and idempotency.
2. Route tests for ``POST /itinerary/{id}/nodes/approve-all`` with a real DB
   session: an advisor and the owning traveler are admitted by the
   writability gate; an unrelated user is 403.

Gated on the local Supabase like its siblings.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Node, NodeHistory, NodeStatus
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ApproveAllResult,
    ItineraryError,
    ItineraryOutcome,
    approve_all_nodes,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"appall-{kind.value}")


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(
    itinerary_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID] | None = None,
    client_ids: list[uuid.UUID] | None = None,
) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for iid in itinerary_ids:
                await conn.execute(
                    text("delete from public.node_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
            for cid in client_ids or []:
                await conn.execute(text("delete from public.clients where id = :i"), {"i": cid})
            for uid in user_ids or []:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": uid})
    finally:
        await engine.dispose()


# ── Service layer ────────────────────────────────────────────────────────────


@integration
async def test_missing_itinerary_is_not_found(db_session: AsyncSession) -> None:
    result = await approve_all_nodes(db_session, _actor(), itinerary_id=uuid.uuid4())
    assert isinstance(result, ItineraryError)
    assert result.outcome is ItineraryOutcome.NOT_FOUND


@integration
async def test_fork_is_refused_with_not_a_trunk(db_session: AsyncSession) -> None:
    trunk = await insert_itinerary(db_session, title="appall trunk")
    fork = await insert_itinerary(db_session, title="appall fork", forked_from_id=trunk)
    try:
        result = await approve_all_nodes(db_session, _actor(), itinerary_id=fork)
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.CONFLICT
        assert result.detail == "not_a_trunk"
    finally:
        await _cleanup([fork, trunk])


@integration
async def test_flips_only_approvable_pending_nodes(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="appall scope")
    try:
        flip_a = await insert_node(db_session, itinerary_id=iid, type="experience", title="a")
        flip_b = await insert_node(db_session, itinerary_id=iid, type="hotel", title="b")
        # Untouchables: annotation kinds, discarded, deselected alt, deleted,
        # and already-firmed statuses.
        note = await insert_node(db_session, itinerary_id=iid, type="note", title="n")
        waiting = await insert_node(db_session, itinerary_id=iid, type="waiting", title="w")
        free = await insert_node(db_session, itinerary_id=iid, type="free_time", title="f")
        discarded = await insert_node(
            db_session, itinerary_id=iid, type="meal", status="discarded", title="d"
        )
        deselected = await insert_node(
            db_session, itinerary_id=iid, type="hotel", title="alt-b", is_selected_alt=False
        )
        ghost = await insert_node(db_session, itinerary_id=iid, type="experience", title="g")
        await db_session.execute(
            text("update public.nodes set deleted_at = now() where id = :n"), {"n": ghost}
        )
        booked = await insert_node(
            db_session, itinerary_id=iid, type="flight", status="booked", title="jl15"
        )
        await db_session.commit()

        result = await approve_all_nodes(db_session, _actor(), itinerary_id=iid)
        assert isinstance(result, ApproveAllResult)
        assert result.approved_count == 2

        statuses = {
            row.id: row.status
            for row in (
                await db_session.execute(
                    select(Node.id, Node.status).where(Node.itinerary_id == iid)
                )
            ).all()
        }
        assert statuses[flip_a] is NodeStatus.approved
        assert statuses[flip_b] is NodeStatus.approved
        assert statuses[note] is NodeStatus.pending
        assert statuses[waiting] is NodeStatus.pending
        assert statuses[free] is NodeStatus.pending
        assert statuses[discarded] is NodeStatus.discarded
        assert statuses[deselected] is NodeStatus.pending
        assert statuses[ghost] is NodeStatus.pending
        assert statuses[booked] is NodeStatus.booked
    finally:
        await _cleanup([iid])


@integration
async def test_writes_one_history_row_per_flipped_node(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="appall audit")
    try:
        flip_a = await insert_node(db_session, itinerary_id=iid, type="experience", title="a")
        flip_b = await insert_node(db_session, itinerary_id=iid, type="meal", title="b")
        await insert_node(db_session, itinerary_id=iid, type="note", title="skip")

        actor = ActorContext(user_id=None, kind=ActorKind.ADVISOR, actor_id="appall-audit-advisor")
        result = await approve_all_nodes(db_session, actor, itinerary_id=iid)
        assert isinstance(result, ApproveAllResult)
        assert result.approved_count == 2

        rows = (
            (await db_session.execute(select(NodeHistory).where(NodeHistory.itinerary_id == iid)))
            .scalars()
            .all()
        )
        # Raw-SQL seeds write no history — the two flips are the only rows.
        assert len(rows) == 2
        assert {r.node_id for r in rows} == {flip_a, flip_b}
        for row in rows:
            assert row.op == "update"
            assert row.actor_kind == ActorKind.ADVISOR.value
            assert row.before is not None and row.before["status"] == "pending"
            assert row.after is not None and row.after["status"] == "approved"
    finally:
        await _cleanup([iid])


@integration
async def test_second_call_is_an_idempotent_noop(db_session: AsyncSession) -> None:
    iid = await insert_itinerary(db_session, title="appall idempotent")
    try:
        await insert_node(db_session, itinerary_id=iid, type="experience", title="a")

        first = await approve_all_nodes(db_session, _actor(), itinerary_id=iid)
        assert isinstance(first, ApproveAllResult)
        assert first.approved_count == 1

        second = await approve_all_nodes(db_session, _actor(), itinerary_id=iid)
        assert isinstance(second, ApproveAllResult)
        assert second.approved_count == 0

        # No extra history rows from the no-op pass.
        count = (
            await db_session.execute(select(NodeHistory.id).where(NodeHistory.itinerary_id == iid))
        ).all()
        assert len(count) == 1
    finally:
        await _cleanup([iid])


# ── Route layer (real DB session; the JWT's profile role decides) ────────────


@pytest.fixture()
def real_db_client() -> Iterator[TestClient]:
    """TestClient whose ``get_session`` binds to the local Supabase.

    A fresh engine per request keeps asyncpg on the TestClient's loop (the
    same pattern as test_roster_pagination.py).
    """

    async def _session() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                yield s
        finally:
            await engine.dispose()

    fastapi_app.dependency_overrides[get_session] = _session
    try:
        with TestClient(fastapi_app) as c:
            yield c
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


async def _seed_route_world() -> dict[str, Any]:
    """An advisor (auth user + advisor profile), a traveler-owned client, and a
    trunk with one pending card, owned by that client."""
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    advisor, traveler, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    client_id = uuid.uuid4()
    try:
        async with maker() as s:
            for uid in (advisor, traveler, stranger):
                await s.execute(
                    text(
                        "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                        "values (:id, :email, false, false)"
                    ),
                    {"id": uid, "email": f"appall-{uid}@test.local"},
                )
            await s.execute(
                text("insert into public.profiles (id, role) values (:id, 'advisor')"),
                {"id": advisor},
            )
            await s.execute(
                text(
                    "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
                    "values (:id, :o, :a, 'Approve All', :e)"
                ),
                {"id": client_id, "o": advisor, "a": traveler, "e": f"appall-{client_id}@x.com"},
            )
            await s.commit()
            iid = await insert_itinerary(s, title="appall route", client_id=client_id)
            await insert_node(s, itinerary_id=iid, type="experience", title="card")
        return {
            "advisor": advisor,
            "traveler": traveler,
            "stranger": stranger,
            "client_id": client_id,
            "itinerary_id": iid,
        }
    finally:
        await engine.dispose()


async def _teardown_route_world(w: dict[str, Any]) -> None:
    await _cleanup(
        [w["itinerary_id"]],
        user_ids=[w["advisor"], w["traveler"], w["stranger"]],
        client_ids=[w["client_id"]],
    )


@integration
async def test_route_advisor_and_owner_allowed_stranger_403(
    real_db_client: TestClient, make_token: Any
) -> None:
    w = await _seed_route_world()
    try:
        url = f"/itinerary/{w['itinerary_id']}/nodes/approve-all"

        # An unrelated authenticated user is refused by the writability gate.
        stranger_headers = {"Authorization": f"Bearer {make_token(sub=str(w['stranger']))}"}
        refused = real_db_client.post(url, headers=stranger_headers)
        assert refused.status_code == 403
        assert refused.json()["detail"] == "forbidden"

        # The owning traveler approves — the traveler's gesture.
        owner_headers = {"Authorization": f"Bearer {make_token(sub=str(w['traveler']))}"}
        approved = real_db_client.post(url, headers=owner_headers)
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["approved_count"] == 1
        assert body["graph"]["itinerary"]["display_status"] == "approved"
        assert all(
            n["status"] == "approved" for n in body["graph"]["nodes"] if n["type"] == "experience"
        )

        # An advisor may repeat it on the client's behalf — idempotent zero.
        advisor_headers = {"Authorization": f"Bearer {make_token(sub=str(w['advisor']))}"}
        again = real_db_client.post(url, headers=advisor_headers)
        assert again.status_code == 200, again.text
        assert again.json()["approved_count"] == 0
    finally:
        await _teardown_route_world(w)
