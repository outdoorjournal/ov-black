"""Itinerary fork — versioned clone with lineage (M004/G2, decision D-FORK).

Two layers:

1. Integration tests against a local Supabase Postgres — the real ``fork_itinerary``
   deep-copies a mixed-status graph: lineage on every node, status transforms
   (approved→pending editable, booked/confirmed carried locked), edge remap,
   PostGIS copy, and baseline independence.
2. Router tests (service stubbed) — the HTTP contract: 201 + the fork graph,
   404 on a missing baseline, 403 when the caller can't fork it, 401 without a JWT.

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import (
    EdgeType,
    ForkStatus,
    Itinerary,
    Node,
    NodeStatus,
    NodeType,
)
from app.services.fork import _forked_status, fork_itinerary
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    add_edge,
    add_node,
    create_itinerary,
    get_itinerary_graph,
    update_node,
)
from sqlalchemy import func, select, text
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


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"fork-{kind.value}")


# ── Pure unit: the status transform ────────────────────────────────────────


@pytest.mark.parametrize(
    ("baseline", "forked"),
    [
        (NodeStatus.pending, NodeStatus.pending),
        (NodeStatus.approved, NodeStatus.pending),  # pre-booked → editable
        (NodeStatus.booked, NodeStatus.booked),  # carried locked
        (NodeStatus.confirmed, NodeStatus.confirmed),  # carried locked
        (NodeStatus.discarded, NodeStatus.discarded),
    ],
)
def test_forked_status_transform(baseline: NodeStatus, forked: NodeStatus) -> None:
    assert _forked_status(baseline) is forked


# ── Integration ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(*itinerary_ids: uuid.UUID) -> None:
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
    finally:
        await engine.dispose()


async def _node(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    *,
    status: NodeStatus,
    title: str,
    type_: NodeType = NodeType.experience,
) -> Node:
    node = await add_node(
        session,
        _actor(ActorKind.SYSTEM),
        itinerary_id=itinerary_id,
        type=type_,
        status=status,
        title=title,
    )
    assert isinstance(node, Node)
    return node


@integration
@pytest.mark.asyncio
async def test_fork_clones_graph_with_lineage(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="Japan")
    fork_id: uuid.UUID | None = None
    try:
        pending = await _node(db_session, baseline.id, status=NodeStatus.pending, title="pend")
        approved = await _node(db_session, baseline.id, status=NodeStatus.approved, title="appr")
        booked = await _node(
            db_session, baseline.id, status=NodeStatus.booked, title="Aman", type_=NodeType.hotel
        )
        await add_edge(
            db_session,
            _actor(),
            itinerary_id=baseline.id,
            from_node_id=approved.id,
            to_node_id=booked.id,
            type=EdgeType.follows,
        )

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        # Fork-level lineage + lifecycle.
        assert fork.forked_from_id == baseline.id
        assert fork.fork_status is ForkStatus.open
        assert fork.client_id == baseline.client_id
        assert fork.id != baseline.id

        view = await get_itinerary_graph(db_session, fork.id)
        assert not isinstance(view, ItineraryError)
        assert len(view.nodes) == 3
        assert len(view.edges) == 1

        by_origin = {n.forked_from_node_id: n for n in view.nodes}
        # Every fork node carries lineage to a distinct baseline node.
        assert set(by_origin) == {pending.id, approved.id, booked.id}

        # Status transforms: approved→pending (editable), booked carried locked.
        assert by_origin[approved.id].status is NodeStatus.pending
        assert by_origin[approved.id].lock_reason is None
        assert by_origin[booked.id].status is NodeStatus.booked
        assert by_origin[booked.id].lock_reason == "status_locked"
        assert by_origin[pending.id].status is NodeStatus.pending

        # The edge was remapped onto the fork's own node ids.
        edge = view.edges[0]
        fork_node_ids = {n.id for n in view.nodes}
        assert edge.from_node_id in fork_node_ids
        assert edge.to_node_id in fork_node_ids
        assert edge.from_node_id == by_origin[approved.id].id
        assert edge.to_node_id == by_origin[booked.id].id
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_fork_is_independent_of_baseline(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="base")
    fork_id: uuid.UUID | None = None
    try:
        original = await _node(db_session, baseline.id, status=NodeStatus.pending, title="keep")
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        fork_view = await get_itinerary_graph(db_session, fork.id)
        assert not isinstance(fork_view, ItineraryError)
        fork_node = fork_view.nodes[0]

        # Edit the fork; the baseline node must be untouched.
        edited = await update_node(
            db_session,
            _actor(),
            itinerary_id=fork.id,
            node_id=fork_node.id,
            title="reworked in the fork",
        )
        assert isinstance(edited, Node)

        baseline_title = (
            await db_session.execute(select(Node.title).where(Node.id == original.id))
        ).scalar_one()
        assert baseline_title == "keep"
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_fork_copies_postgis_location(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="geo")
    fork_id: uuid.UUID | None = None
    try:
        node = await _node(db_session, baseline.id, status=NodeStatus.pending, title="Tokyo")
        # Stamp a PostGIS point the ORM can't see, then fork.
        await db_session.execute(
            text(
                "update public.nodes set location = "
                "ST_SetSRID(ST_MakePoint(139.6917, 35.6895), 4326)::geography "
                "where id = :i"
            ),
            {"i": node.id},
        )
        await db_session.commit()

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        # The fork's copied node carries the same point (lineage-joined copy).
        lon = (
            await db_session.execute(
                text(
                    "select ST_X(location::geometry) from public.nodes "
                    "where itinerary_id = :i and location is not null"
                ),
                {"i": fork.id},
            )
        ).scalar_one()
        assert round(float(lon), 4) == 139.6917
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_fork_missing_baseline_returns_not_found(db_session: AsyncSession) -> None:
    result = await fork_itinerary(db_session, _actor(), itinerary_id=uuid.uuid4())
    assert isinstance(result, ItineraryError)
    assert result.outcome is ItineraryOutcome.NOT_FOUND


# ── Idempotence per (baseline, user) — D030's lazy-fork model, enforced ─────
#
# `created_by` carries an FK to auth.users, so attributable actors need a real
# auth row (same convention as test_me.py).


async def _seed_auth_user(session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": user_id, "email": f"{user_id}@fork-test.local"},
    )
    await session.commit()
    return user_id


async def _cleanup_users(*user_ids: uuid.UUID) -> None:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            for uid in user_ids:
                await conn.execute(text("delete from auth.users where id = :i"), {"i": uid})
    finally:
        await engine.dispose()


def _user_actor(user_id: uuid.UUID) -> ActorContext:
    return ActorContext(user_id=user_id, kind=ActorKind.USER, actor_id=str(user_id))


@integration
@pytest.mark.asyncio
async def test_fork_reuses_the_callers_open_fork(db_session: AsyncSession) -> None:
    """Same user + same baseline → the SAME open fork back, never a twin.

    A different user still gets their own working copy, and once the first
    fork leaves ``open`` (abandoned here) the next call mints a fresh one.
    """
    alice = await _seed_auth_user(db_session)
    bob = await _seed_auth_user(db_session)
    baseline = await create_itinerary(db_session, _actor(), title="Olympus")
    fork_ids: set[uuid.UUID] = set()
    try:
        first = await fork_itinerary(db_session, _user_actor(alice), itinerary_id=baseline.id)
        assert isinstance(first, Itinerary)
        fork_ids.add(first.id)

        again = await fork_itinerary(db_session, _user_actor(alice), itinerary_id=baseline.id)
        assert isinstance(again, Itinerary)
        fork_ids.add(again.id)
        assert again.id == first.id  # reused, not duplicated

        theirs = await fork_itinerary(db_session, _user_actor(bob), itinerary_id=baseline.id)
        assert isinstance(theirs, Itinerary)
        fork_ids.add(theirs.id)
        assert theirs.id != first.id  # another user's working copy is their own

        # Closing the fork releases the slot: the next fork is a fresh copy.
        first.fork_status = ForkStatus.abandoned
        await db_session.commit()
        fresh = await fork_itinerary(db_session, _user_actor(alice), itinerary_id=baseline.id)
        assert isinstance(fresh, Itinerary)
        fork_ids.add(fresh.id)
        assert fresh.id != first.id
    finally:
        await _cleanup(*fork_ids, baseline.id)
        await _cleanup_users(alice, bob)


@integration
@pytest.mark.asyncio
async def test_concurrent_forks_collapse_to_one(db_session: AsyncSession) -> None:
    """N truly concurrent forks by one user yield ONE fork (advisory lock).

    Regression for the double-fork incident: two in-flight renders both read
    "no open fork yet" and each minted one, stranding the first fork's chat
    sessions. Serialized, the losers block, re-read, and reuse the winner's.
    """
    user = await _seed_auth_user(db_session)
    baseline = await create_itinerary(db_session, _actor(), title="racy")
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async def fork_once() -> uuid.UUID:
        async with maker() as s:
            result = await fork_itinerary(s, _user_actor(user), itinerary_id=baseline.id)
            assert isinstance(result, Itinerary)
            return result.id

    try:
        ids = set(await asyncio.gather(*(fork_once() for _ in range(4))))
        assert len(ids) == 1
        open_count = (
            await db_session.execute(
                select(func.count())
                .select_from(Itinerary)
                .where(
                    Itinerary.forked_from_id == baseline.id,
                    Itinerary.fork_status == ForkStatus.open,
                )
            )
        ).scalar_one()
        assert open_count == 1
    finally:
        await engine.dispose()
        forks = (
            (
                await db_session.execute(
                    select(Itinerary.id).where(Itinerary.forked_from_id == baseline.id)
                )
            )
            .scalars()
            .all()
        )
        await _cleanup(*forks, baseline.id)
        await _cleanup_users(user)


# ── Router (service stubbed) ───────────────────────────────────────────────


@pytest.fixture()
def fork_routes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the fork endpoint's collaborators off a fake session."""
    from app.db import get_session
    from app.main import app as fastapi_app
    from app.routers import itineraries as ri

    calls: dict[str, list[Any]] = {"fork": []}
    returns: dict[str, Any] = {"forkable": True, "baseline": object()}

    async def _load(_s: Any, iid: uuid.UUID) -> Any:
        return returns.get("baseline")

    async def _forkable(_s: Any, _u: Any, _itin: Any) -> None:
        if not returns.get("forkable", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")

    async def _is_advisor(_s: Any, _uid: Any) -> bool:
        return False

    async def _fork(_s: Any, actor: Any, *, itinerary_id: uuid.UUID, title: Any = None) -> Any:
        calls["fork"].append({"itinerary_id": itinerary_id, "title": title, "actor": actor})
        return returns.get("fork_result") or Itinerary(id=uuid.uuid4(), title="forked")

    async def _graph(_s: Any, iid: uuid.UUID) -> Any:
        from app.services.itineraries import GraphView

        return returns.get(
            "graph",
            GraphView(
                itinerary=Itinerary(
                    id=iid, title="forked", forked_from_id=uuid.uuid4(), fork_status=ForkStatus.open
                ),
                nodes=[],
                edges=[],
            ),
        )

    monkeypatch.setattr(ri, "_load_itinerary", _load)
    monkeypatch.setattr(ri, "assert_itinerary_forkable", _forkable)
    monkeypatch.setattr(ri, "_is_requester_advisor", _is_advisor)
    monkeypatch.setattr(ri, "fork_itinerary", _fork)
    monkeypatch.setattr(ri, "get_itinerary_graph", _graph)

    async def _dep() -> Any:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield {"calls": calls, "returns": returns}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


def _headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


def test_fork_endpoint_requires_jwt(client: Any, fork_routes: dict[str, Any]) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/fork", json={})
    assert resp.status_code == 401


def test_fork_endpoint_201_returns_fork_graph(
    client: Any, fork_routes: dict[str, Any], make_token: Any
) -> None:
    iid = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{iid}/fork", json={"title": "Slower trip"}, headers=_headers(make_token)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["itinerary"]["forked_from_id"] is not None
    assert body["itinerary"]["fork_status"] == "open"
    assert fork_routes["calls"]["fork"][-1]["itinerary_id"] == iid
    assert fork_routes["calls"]["fork"][-1]["title"] == "Slower trip"


def test_fork_endpoint_404_when_baseline_missing(
    client: Any, fork_routes: dict[str, Any], make_token: Any
) -> None:
    fork_routes["returns"]["baseline"] = None
    resp = client.post(f"/itinerary/{uuid.uuid4()}/fork", json={}, headers=_headers(make_token))
    assert resp.status_code == 404


def test_fork_endpoint_403_when_not_forkable(
    client: Any, fork_routes: dict[str, Any], make_token: Any
) -> None:
    fork_routes["returns"]["forkable"] = False
    resp = client.post(f"/itinerary/{uuid.uuid4()}/fork", json={}, headers=_headers(make_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"
