"""Fork diff + reconcile (M004/G3) — the staff fold-back surface.

Two layers, mirroring ``test_fork.py``:

1. Integration tests against a local Supabase Postgres — ``diff_fork`` buckets a
   real divergence (added/removed/changed/moved, with the intrinsic
   approved→proposed demotion *excluded*), ``reconcile_fork`` folds accepted
   changes into the live baseline through the G1-gated service path (a booked
   baseline node is refused, not applied), the feasibility gate refuses a fork
   carrying a ``block`` finding, and ``request_reconcile`` / ``abandon_fork``
   stamp + clear the request.
2. Router tests (service stubbed) — the four HTTP contracts incl. advisor-only
   reconcile (403 for a non-advisor) and 401 without a JWT.

Gated on ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import socket
import uuid
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.models import (
    Analysis,
    AnalysisFinding,
    AnalysisStatus,
    EdgeType,
    FindingSeverity,
    ForkStatus,
    Itinerary,
    Node,
    NodeStatus,
    NodeType,
)
from app.services.fork import (
    ForkDiff,
    NodeChange,
    ReconcileDecision,
    ReconcileOutcome,
    ReconcileResult,
    abandon_fork,
    diff_fork,
    fork_itinerary,
    reconcile_fork,
    request_reconcile,
)
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    add_edge,
    add_node,
    create_itinerary,
    delete_node,
    get_itinerary_graph,
    update_node,
)
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


def _actor(kind: ActorKind = ActorKind.ADVISOR) -> ActorContext:
    return ActorContext(user_id=None, kind=kind, actor_id=f"recon-{kind.value}")


# ── Integration harness ──────────────────────────────────────────────────────


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
        _actor(),
        itinerary_id=itinerary_id,
        type=type_,
        status=status,
        title=title,
    )
    assert isinstance(node, Node)
    return node


def _fork_node_for(view: Any, origin_id: uuid.UUID) -> Any:
    """The fork node whose lineage points at ``origin_id`` (None if absent)."""
    return next((n for n in view.nodes if n.forked_from_node_id == origin_id), None)


# ── diff_fork ────────────────────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_diff_buckets_added_removed_changed_moved(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="diff")
    fork_id: uuid.UUID | None = None
    try:
        keep = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="keep")
        appr = await _node(db_session, baseline.id, status=NodeStatus.approved, title="appr")
        remove = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="remove")
        p = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="p")
        q = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="q")

        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        fview = await get_itinerary_graph(db_session, fork.id)
        assert not isinstance(fview, ItineraryError)

        # changed: edit the forked 'keep' node's title.
        keep_fork = _fork_node_for(fview, keep.id)
        await update_node(
            db_session, _actor(), itinerary_id=fork.id, node_id=keep_fork.id, title="keep-reworked"
        )
        # removed: delete the forked 'remove' node.
        remove_fork = _fork_node_for(fview, remove.id)
        await delete_node(db_session, _actor(), itinerary_id=fork.id, node_id=remove_fork.id)
        # moved: wire a follows edge p→q in the fork (neither had one in baseline).
        p_fork = _fork_node_for(fview, p.id)
        q_fork = _fork_node_for(fview, q.id)
        await add_edge(
            db_session,
            _actor(),
            itinerary_id=fork.id,
            from_node_id=p_fork.id,
            to_node_id=q_fork.id,
            type=EdgeType.follows,
        )
        # added: a brand-new node, native to the fork (no lineage).
        added_node = await _node(db_session, fork.id, status=NodeStatus.proposed, title="added")

        diff = await diff_fork(db_session, fork_id=fork.id)
        assert isinstance(diff, ForkDiff)

        assert {c.baseline_node_id for c in diff.removed} == {remove.id}
        assert {c.fork_node_id for c in diff.added} == {added_node.id}
        assert len(diff.changed) == 1
        assert diff.changed[0].baseline_node_id == keep.id
        assert "title" in diff.changed[0].fields
        assert "status" not in diff.changed[0].fields  # only the title was edited
        moved_origins = {c.baseline_node_id for c in diff.moved}
        assert moved_origins and moved_origins <= {p.id, q.id}

        # The intrinsic approved→proposed fork demotion is NOT a reported change.
        touched = {c.baseline_node_id for c in (*diff.changed, *diff.moved, *diff.removed)}
        assert appr.id not in touched
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_diff_rejects_non_fork(db_session: AsyncSession) -> None:
    plain = await create_itinerary(db_session, _actor(), title="plain")
    try:
        result = await diff_fork(db_session, fork_id=plain.id)
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
        assert result.detail == "not_a_fork"
    finally:
        await _cleanup(plain.id)


# ── reconcile_fork ───────────────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_reconcile_applies_accepted_discards_rest(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="recon")
    fork_id: uuid.UUID | None = None
    try:
        e1 = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="e1")
        e2 = await _node(db_session, baseline.id, status=NodeStatus.proposed, title="e2")
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        fview = await get_itinerary_graph(db_session, fork.id)
        assert not isinstance(fview, ItineraryError)
        e1_fork = _fork_node_for(fview, e1.id)
        e2_fork = _fork_node_for(fview, e2.id)
        await update_node(
            db_session, _actor(), itinerary_id=fork.id, node_id=e1_fork.id, title="e1-new"
        )
        await update_node(
            db_session, _actor(), itinerary_id=fork.id, node_id=e2_fork.id, title="e2-new"
        )

        diff = await diff_fork(db_session, fork_id=fork.id)
        assert isinstance(diff, ForkDiff)
        by_origin = {c.baseline_node_id: c for c in diff.changed}
        decisions = [
            ReconcileDecision(change_id=by_origin[e1.id].change_id, accept=True),
            ReconcileDecision(change_id=by_origin[e2.id].change_id, accept=False),
        ]
        result = await reconcile_fork(
            db_session, _actor(ActorKind.ADVISOR), fork_id=fork.id, decisions=decisions
        )
        assert isinstance(result, ReconcileResult)

        results = {o.change_id: o.result for o in result.outcomes}
        assert results[by_origin[e1.id].change_id] == "applied"
        assert results[by_origin[e2.id].change_id] == "discarded"

        # Baseline reflects only the accepted change.
        live = await get_itinerary_graph(db_session, baseline.id)
        assert not isinstance(live, ItineraryError)
        titles = {n.id: n.title for n in live.nodes}
        assert titles[e1.id] == "e1-new"
        assert titles[e2.id] == "e2"

        # Every change decided, none refused → the fork is reconciled.
        assert result.fork.fork_status is ForkStatus.reconciled
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_reconcile_refuses_booked_baseline_node(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="booked")
    fork_id: uuid.UUID | None = None
    try:
        bk = await _node(db_session, baseline.id, status=NodeStatus.approved, title="bk")
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        fview = await get_itinerary_graph(db_session, fork.id)
        assert not isinstance(fview, ItineraryError)
        bk_fork = _fork_node_for(fview, bk.id)  # demoted approved→proposed in the fork
        await update_node(
            db_session, _actor(), itinerary_id=fork.id, node_id=bk_fork.id, title="bk-reworked"
        )
        # Meanwhile the baseline node gets booked. update_node now refuses a direct
        # →booked flip (M005/I3: the money gate is the only path; see test_bookings.py),
        # so seed the booked status straight on the row for this reconcile setup.
        bk_row = await db_session.get(Node, bk.id)
        assert bk_row is not None
        bk_row.status = NodeStatus.booked
        await db_session.commit()

        diff = await diff_fork(db_session, fork_id=fork.id)
        assert isinstance(diff, ForkDiff)
        change = next(c for c in diff.changed if c.baseline_node_id == bk.id)
        result = await reconcile_fork(
            db_session,
            _actor(ActorKind.ADVISOR),
            fork_id=fork.id,
            decisions=[ReconcileDecision(change_id=change.change_id, accept=True)],
        )
        assert isinstance(result, ReconcileResult)
        assert result.outcomes[0].result == "refused_booked"

        # The booked baseline node is untouched, and the fork stays open (it still diverges).
        live = await get_itinerary_graph(db_session, baseline.id)
        assert not isinstance(live, ItineraryError)
        bk_live = next(n for n in live.nodes if n.id == bk.id)
        assert bk_live.title == "bk"
        assert bk_live.status is NodeStatus.booked
        assert result.fork.fork_status is ForkStatus.open
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_reconcile_feasibility_gate_blocks_without_override(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="feas")
    fork_id: uuid.UUID | None = None
    try:
        await _node(db_session, baseline.id, status=NodeStatus.proposed, title="n")
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id
        # A completed Analyze on the fork carrying a block finding.
        analysis = Analysis(itinerary_id=fork.id, status=AnalysisStatus.completed)
        db_session.add(analysis)
        await db_session.flush()
        db_session.add(
            AnalysisFinding(
                analysis_id=analysis.id,
                severity=FindingSeverity.block,
                category="geo",
                message="impossible drive",
            )
        )
        await db_session.commit()

        blocked = await reconcile_fork(
            db_session, _actor(ActorKind.ADVISOR), fork_id=fork.id, decisions=[]
        )
        assert isinstance(blocked, ItineraryError)
        assert blocked.outcome is ItineraryOutcome.VALIDATION_ERROR
        assert blocked.detail == "fork_infeasible"

        # The advisor's explicit override gets past the block.
        overridden = await reconcile_fork(
            db_session,
            _actor(ActorKind.ADVISOR),
            fork_id=fork.id,
            decisions=[],
            override_block=True,
        )
        assert isinstance(overridden, ReconcileResult)
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


# ── request / abandon ────────────────────────────────────────────────────────


@integration
@pytest.mark.asyncio
async def test_request_then_abandon_stamps_and_clears(db_session: AsyncSession) -> None:
    baseline = await create_itinerary(db_session, _actor(), title="req")
    fork_id: uuid.UUID | None = None
    try:
        fork = await fork_itinerary(db_session, _actor(), itinerary_id=baseline.id)
        assert isinstance(fork, Itinerary)
        fork_id = fork.id

        requested = await request_reconcile(
            db_session, _actor(ActorKind.USER), fork_id=fork.id, note="prefer the slower version"
        )
        assert isinstance(requested, Itinerary)
        assert requested.reconcile_requested_at is not None
        assert requested.reconcile_request_note == "prefer the slower version"

        abandoned = await abandon_fork(db_session, _actor(ActorKind.ADVISOR), fork_id=fork.id)
        assert isinstance(abandoned, Itinerary)
        assert abandoned.fork_status is ForkStatus.abandoned
        assert abandoned.reconcile_requested_at is None
        assert abandoned.reconcile_request_note is None
    finally:
        await _cleanup(*(i for i in (fork_id, baseline.id) if i is not None))


@integration
@pytest.mark.asyncio
async def test_request_reconcile_rejects_non_fork(db_session: AsyncSession) -> None:
    plain = await create_itinerary(db_session, _actor(), title="plain")
    try:
        result = await request_reconcile(db_session, _actor(ActorKind.USER), fork_id=plain.id)
        assert isinstance(result, ItineraryError)
        assert result.detail == "not_a_fork"
    finally:
        await _cleanup(plain.id)


# ── Router (service stubbed) ───────────────────────────────────────────────


@pytest.fixture()
def recon_routes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the diff/reconcile/request/abandon endpoints' collaborators."""
    from app.auth import AuthenticatedUser
    from app.auth_guards import require_advisor
    from app.db import get_session
    from app.main import app as fastapi_app
    from app.routers import itineraries as ri
    from app.services.itineraries import GraphView

    calls: dict[str, list[Any]] = {"reconcile": [], "request": [], "abandon": []}
    returns: dict[str, Any] = {"forkable": True, "baseline": object(), "is_advisor": True}

    async def _load(_s: Any, iid: uuid.UUID) -> Any:
        return returns.get("baseline")

    async def _forkable(_s: Any, _u: Any, _itin: Any) -> None:
        if not returns.get("forkable", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")

    async def _is_advisor(_s: Any, _uid: Any) -> bool:
        return bool(returns.get("is_advisor", True))

    async def _diff(_s: Any, *, fork_id: uuid.UUID) -> Any:
        return ForkDiff(
            fork_id=fork_id,
            baseline_id=uuid.uuid4(),
            added=[
                NodeChange(
                    change_id=uuid.uuid4(),
                    kind="added",
                    fork_node_id=uuid.uuid4(),
                    baseline_node_id=None,
                    fields=(),
                    before=None,
                    after={"title": "new"},
                )
            ],
            removed=[],
            changed=[],
            moved=[],
        )

    async def _reconcile(_s: Any, actor: Any, **kw: Any) -> Any:
        calls["reconcile"].append(kw)
        return ReconcileResult(
            itinerary=Itinerary(id=uuid.uuid4(), title="baseline"),
            fork=Itinerary(id=kw["fork_id"], title="fork", fork_status=ForkStatus.reconciled),
            outcomes=[ReconcileOutcome(change_id=uuid.uuid4(), kind="changed", result="applied")],
        )

    async def _graph(_s: Any, iid: uuid.UUID) -> Any:
        return GraphView(itinerary=Itinerary(id=iid, title="baseline"), nodes=[], edges=[])

    async def _request(_s: Any, actor: Any, *, fork_id: uuid.UUID, note: Any = None) -> Any:
        calls["request"].append({"fork_id": fork_id, "note": note})
        return Itinerary(id=fork_id, title="fork", forked_from_id=uuid.uuid4())

    async def _abandon(_s: Any, actor: Any, *, fork_id: uuid.UUID) -> Any:
        calls["abandon"].append({"fork_id": fork_id})
        return Itinerary(id=fork_id, title="fork", fork_status=ForkStatus.abandoned)

    monkeypatch.setattr(ri, "_load_itinerary", _load)
    monkeypatch.setattr(ri, "assert_itinerary_forkable", _forkable)
    monkeypatch.setattr(ri, "_is_requester_advisor", _is_advisor)
    monkeypatch.setattr(ri, "diff_fork", _diff)
    monkeypatch.setattr(ri, "reconcile_fork", _reconcile)
    monkeypatch.setattr(ri, "get_itinerary_graph", _graph)
    monkeypatch.setattr(ri, "request_reconcile", _request)
    monkeypatch.setattr(ri, "abandon_fork", _abandon)

    async def _dep() -> Any:
        yield object()

    advisor_user = AuthenticatedUser(
        sub=str(uuid.uuid4()), email="a@x.com", role="authenticated", claims={}
    )

    async def _require_advisor() -> Any:
        if not returns.get("is_advisor", True):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="advisor_only")
        return advisor_user

    fastapi_app.dependency_overrides[get_session] = _dep
    fastapi_app.dependency_overrides[require_advisor] = _require_advisor
    try:
        yield {"calls": calls, "returns": returns}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(require_advisor, None)


def _headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


def test_diff_endpoint_200(client: Any, recon_routes: dict[str, Any], make_token: Any) -> None:
    resp = client.get(f"/itinerary/{uuid.uuid4()}/diff", headers=_headers(make_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["added"]) == 1
    assert body["added"][0]["kind"] == "added"


def test_diff_endpoint_requires_jwt(client: Any, recon_routes: dict[str, Any]) -> None:
    assert client.get(f"/itinerary/{uuid.uuid4()}/diff").status_code == 401


def test_diff_endpoint_404_when_missing(
    client: Any, recon_routes: dict[str, Any], make_token: Any
) -> None:
    recon_routes["returns"]["baseline"] = None
    resp = client.get(f"/itinerary/{uuid.uuid4()}/diff", headers=_headers(make_token))
    assert resp.status_code == 404


def test_reconcile_endpoint_200(client: Any, recon_routes: dict[str, Any], make_token: Any) -> None:
    fork_id = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{fork_id}/reconcile",
        json={"decisions": [{"change_id": str(uuid.uuid4()), "accept": True}]},
        headers=_headers(make_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fork"]["fork_status"] == "reconciled"
    assert body["outcomes"][0]["result"] == "applied"
    assert recon_routes["calls"]["reconcile"][-1]["fork_id"] == fork_id


def test_reconcile_endpoint_advisor_only_403(
    client: Any, recon_routes: dict[str, Any], make_token: Any
) -> None:
    recon_routes["returns"]["is_advisor"] = False
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/reconcile",
        json={"decisions": []},
        headers=_headers(make_token),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "advisor_only"


def test_reconcile_endpoint_requires_jwt(client: Any, recon_routes: dict[str, Any]) -> None:
    assert (
        client.post(f"/itinerary/{uuid.uuid4()}/reconcile", json={"decisions": []}).status_code
        == 401
    )


def test_request_reconcile_endpoint_200(
    client: Any, recon_routes: dict[str, Any], make_token: Any
) -> None:
    fork_id = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{fork_id}/request-reconcile",
        json={"note": "slower please"},
        headers=_headers(make_token),
    )
    assert resp.status_code == 200, resp.text
    assert recon_routes["calls"]["request"][-1]["note"] == "slower please"


def test_abandon_endpoint_200(client: Any, recon_routes: dict[str, Any], make_token: Any) -> None:
    fork_id = uuid.uuid4()
    resp = client.post(f"/itinerary/{fork_id}/abandon", headers=_headers(make_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["fork_status"] == "abandoned"
    assert recon_routes["calls"]["abandon"][-1]["fork_id"] == fork_id
