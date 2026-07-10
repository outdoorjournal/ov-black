"""Trunk guard (0044) — official trunks accept content only via publish.

``_check_write_gates`` refuses USER/AGENT content mutations on a trunk
(``forked_from_id IS NULL``) with ``TRUNK_LOCKED`` / ``fork_required``; pure
node-status changes, ADVISOR, and SYSTEM are exempt, and forks are unaffected.

Coverage:

- every content mutation (add_node / update_node content / delete_node /
  add_edge) by USER and AGENT on a trunk → TRUNK_LOCKED (route: 409
  ``fork_required``);
- pure status flips (approve / discard) by USER on a trunk succeed;
- ADVISOR content edits on a trunk succeed (the deliberate escape hatch);
- the same USER mutations all succeed on a fork;
- reconcile (advisor path) still writes accepted fork changes into the trunk;
- ``_persist_proposed_card`` with a trunk-pinned session lands the card in
  the client's lazily-created fork — never on the trunk.

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
from app.models import EdgeType, ForkStatus, Itinerary, Node, NodeStatus, NodeType
from app.services.agent import _persist_proposed_card
from app.services.fork import ReconcileDecision, ReconcileResult, fork_itinerary, reconcile_fork
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    Edge,
    ItineraryError,
    ItineraryOutcome,
    add_edge,
    add_node,
    delete_node,
    get_itinerary_graph,
    update_node,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, insert_node, integration


def _actor(kind: ActorKind) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"trunk-{kind.value}")


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
                await conn.execute(
                    text("delete from public.edge_history where itinerary_id = :i"), {"i": iid}
                )
                await conn.execute(text("delete from public.itineraries where id = :i"), {"i": iid})
            for cid in client_ids or []:
                await conn.execute(
                    text("delete from public.agent_sessions where client_id = :i"), {"i": cid}
                )
                await conn.execute(text("delete from public.clients where id = :i"), {"i": cid})
            for uid in user_ids or []:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": uid})
    finally:
        await engine.dispose()


def _assert_trunk_locked(result: Any) -> None:
    assert isinstance(result, ItineraryError)
    assert result.outcome is ItineraryOutcome.TRUNK_LOCKED
    assert result.detail == "fork_required"


async def _run_content_mutations(
    session: AsyncSession,
    actor: ActorContext,
    *,
    itinerary_id: uuid.UUID,
    node_id: uuid.UUID,
    edge_target_id: uuid.UUID,
) -> list[Any]:
    """(add_node, update_node-content, delete_node, add_edge) results."""
    added = await add_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        type=NodeType.experience,
        title="new card",
    )
    edited = await update_node(
        session,
        actor,
        itinerary_id=itinerary_id,
        node_id=node_id,
        title="renamed",
    )
    deleted = await delete_node(session, actor, itinerary_id=itinerary_id, node_id=node_id)
    edged = await add_edge(
        session,
        actor,
        itinerary_id=itinerary_id,
        from_node_id=node_id,
        to_node_id=edge_target_id,
        type=EdgeType.follows,
    )
    return [added, edited, deleted, edged]


# ── USER / AGENT content mutations on a trunk are refused ────────────────────


@integration
@pytest.mark.parametrize("kind", [ActorKind.USER, ActorKind.AGENT])
async def test_content_mutations_on_trunk_are_trunk_locked(
    db_session: AsyncSession, kind: ActorKind
) -> None:
    trunk = await insert_itinerary(db_session, title="guarded trunk")
    try:
        a = await insert_node(db_session, itinerary_id=trunk, type="experience", title="a")
        b = await insert_node(db_session, itinerary_id=trunk, type="meal", title="b")
        results = await _run_content_mutations(
            db_session, _actor(kind), itinerary_id=trunk, node_id=a, edge_target_id=b
        )
        for result in results:
            _assert_trunk_locked(result)
        # Nothing changed on the trunk.
        view = await get_itinerary_graph(db_session, trunk)
        assert not isinstance(view, ItineraryError)
        assert {n.title for n in view.nodes} == {"a", "b"}
        assert view.edges == []
    finally:
        await _cleanup([trunk])


# ── Pure status flips by USER on a trunk still work ──────────────────────────


@integration
async def test_user_status_flips_on_trunk_succeed(db_session: AsyncSession) -> None:
    trunk = await insert_itinerary(db_session, title="approvable trunk")
    try:
        approve_me = await insert_node(db_session, itinerary_id=trunk, type="experience", title="x")
        discard_me = await insert_node(db_session, itinerary_id=trunk, type="meal", title="y")

        approved = await update_node(
            db_session,
            _actor(ActorKind.USER),
            itinerary_id=trunk,
            node_id=approve_me,
            status=NodeStatus.approved,
        )
        assert isinstance(approved, Node)
        assert approved.status is NodeStatus.approved

        discarded = await update_node(
            db_session,
            _actor(ActorKind.USER),
            itinerary_id=trunk,
            node_id=discard_me,
            status=NodeStatus.discarded,
        )
        assert isinstance(discarded, Node)
        assert discarded.status is NodeStatus.discarded
    finally:
        await _cleanup([trunk])


# ── ADVISOR content edits on a trunk succeed ─────────────────────────────────


@integration
async def test_advisor_content_edit_on_trunk_succeeds(db_session: AsyncSession) -> None:
    trunk = await insert_itinerary(db_session, title="advisor trunk")
    try:
        nid = await insert_node(db_session, itinerary_id=trunk, type="experience", title="orig")
        edited = await update_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=trunk,
            node_id=nid,
            title="advisor rework",
        )
        assert isinstance(edited, Node)
        assert edited.title == "advisor rework"

        added = await add_node(
            db_session,
            _actor(ActorKind.ADVISOR),
            itinerary_id=trunk,
            type=NodeType.meal,
            title="advisor addition",
        )
        assert isinstance(added, Node)
    finally:
        await _cleanup([trunk])


# ── The same USER mutations succeed on a fork ────────────────────────────────


@integration
async def test_user_content_mutations_on_fork_succeed(db_session: AsyncSession) -> None:
    trunk = await insert_itinerary(db_session, title="fork parent")
    fork = await insert_itinerary(db_session, title="working fork", forked_from_id=trunk)
    try:
        a = await insert_node(db_session, itinerary_id=fork, type="experience", title="a")
        b = await insert_node(db_session, itinerary_id=fork, type="meal", title="b")
        added, edited, deleted, edged = await _run_content_mutations(
            db_session, _actor(ActorKind.USER), itinerary_id=fork, node_id=a, edge_target_id=b
        )
        assert isinstance(added, Node)
        assert isinstance(edited, Node)
        assert edited.title == "renamed"
        assert deleted is None  # delete_node returns None on success
        assert isinstance(edged, Edge)
    finally:
        await _cleanup([fork, trunk])


# ── Reconcile (advisor path) still writes the trunk ──────────────────────────


@integration
async def test_reconcile_applies_fork_changes_to_the_trunk(db_session: AsyncSession) -> None:
    trunk = await insert_itinerary(db_session, title="publishable trunk")
    fork_id: uuid.UUID | None = None
    try:
        baseline_node = await insert_node(
            db_session, itinerary_id=trunk, type="experience", title="draft card"
        )
        fork = await fork_itinerary(db_session, _actor(ActorKind.ADVISOR), itinerary_id=trunk)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        fview = await get_itinerary_graph(db_session, fork_id)
        assert not isinstance(fview, ItineraryError)
        fork_node = next(n for n in fview.nodes if n.forked_from_node_id == baseline_node)
        # The traveler reworks the card in THEIR fork (allowed)…
        reworked = await update_node(
            db_session,
            _actor(ActorKind.USER),
            itinerary_id=fork_id,
            node_id=fork_node.id,
            title="published card",
        )
        assert isinstance(reworked, Node)

        # …and the advisor publishes: reconcile folds it into the trunk.
        result = await reconcile_fork(
            db_session,
            _actor(ActorKind.ADVISOR),
            fork_id=fork_id,
            decisions=[ReconcileDecision(change_id=fork_node.id, accept=True)],
        )
        assert isinstance(result, ReconcileResult)
        assert [o.result for o in result.outcomes] == ["applied"]

        trunk_title = (
            await db_session.execute(select(Node.title).where(Node.id == baseline_node))
        ).scalar_one()
        assert trunk_title == "published card"
    finally:
        await _cleanup([i for i in (fork_id, trunk) if i is not None])


# ── Agent cards land in the client's lazily-created fork ─────────────────────


@integration
async def test_persist_proposed_card_lands_in_lazily_created_fork(
    db_session: AsyncSession,
) -> None:
    traveler = uuid.uuid4()
    client_id = uuid.uuid4()
    session_id = uuid.uuid4()
    trunk: uuid.UUID | None = None
    fork_id: uuid.UUID | None = None
    try:
        await db_session.execute(
            text(
                "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                "values (:id, :email, false, false)"
            ),
            {"id": traveler, "email": f"trunk-{traveler}@test.local"},
        )
        await db_session.execute(
            text(
                "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
                "values (:id, :o, :a, 'Trunk Guard', :e)"
            ),
            {"id": client_id, "o": traveler, "a": traveler, "e": f"trunk-{client_id}@x.com"},
        )
        await db_session.commit()
        trunk = await insert_itinerary(db_session, title="pinned trunk", client_id=client_id)
        await db_session.execute(
            text(
                "insert into public.agent_sessions (id, client_id, agentcore_session_id) "
                "values (:id, :c, :acs)"
            ),
            {"id": session_id, "c": client_id, "acs": f"acs-{session_id}"},
        )
        await db_session.commit()

        node_id = await _persist_proposed_card(
            db_session,
            session_id=session_id,
            itinerary_id=trunk,
            agentcore_session_id=f"acs-{session_id}",
            source="ov",
            source_id="exp-1",
            snapshot={"title": "Kaiseki dinner"},
        )
        assert node_id is not None

        # A fork of the trunk exists, created for the client's auth user.
        fork_row = (
            await db_session.execute(select(Itinerary).where(Itinerary.forked_from_id == trunk))
        ).scalar_one()
        fork_id = fork_row.id
        assert fork_row.created_by == traveler
        assert fork_row.fork_status is ForkStatus.open

        # The node is in the fork — the trunk stayed clean.
        node_row = (await db_session.execute(select(Node).where(Node.id == node_id))).scalar_one()
        assert node_row.itinerary_id == fork_id
        assert node_row.status is NodeStatus.pending
        trunk_nodes = (
            await db_session.execute(select(Node.id).where(Node.itinerary_id == trunk))
        ).all()
        assert trunk_nodes == []

        # A second card reuses the SAME fork — no duplicate fork per card.
        second = await _persist_proposed_card(
            db_session,
            session_id=session_id,
            itinerary_id=trunk,
            agentcore_session_id=f"acs-{session_id}",
            source="ov",
            source_id="exp-2",
            snapshot={"title": "Tea ceremony"},
        )
        assert second is not None
        forks = (
            await db_session.execute(select(Itinerary.id).where(Itinerary.forked_from_id == trunk))
        ).all()
        assert len(forks) == 1
    finally:
        await _cleanup(
            [i for i in (fork_id, trunk) if i is not None],
            user_ids=[traveler],
            client_ids=[client_id],
        )


# ── Route: 409 fork_required for a USER content write on a trunk ─────────────


@pytest.fixture()
def real_db_client() -> Iterator[TestClient]:
    """TestClient whose ``get_session`` binds to the local Supabase (fresh
    engine per request so asyncpg stays on the TestClient's loop)."""

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


@integration
async def test_route_user_node_write_on_trunk_is_409_fork_required(
    real_db_client: TestClient, make_token: Any
) -> None:
    creator = uuid.uuid4()
    trunk: uuid.UUID | None = None
    try:
        engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                await s.execute(
                    text(
                        "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                        "values (:id, :email, false, false)"
                    ),
                    {"id": creator, "email": f"trunk-{creator}@test.local"},
                )
                await s.commit()
                trunk = await insert_itinerary(s, title="route trunk", created_by=creator)
        finally:
            await engine.dispose()

        # The creator passes the writability gate but is still a USER — the
        # trunk guard refuses the content write with the fork signal.
        headers = {"Authorization": f"Bearer {make_token(sub=str(creator))}"}
        resp = real_db_client.post(
            f"/itinerary/{trunk}/nodes",
            json={"type": "experience", "title": "blocked"},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "fork_required"
    finally:
        await _cleanup([i for i in (trunk,) if i is not None], user_ids=[creator])
