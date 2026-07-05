"""HTTP contract for the S08 lock / release / approve / assemble routes.

The service layer is exercised end-to-end in ``test_itinerary_approval_race.py``
(real Postgres). These tests pin the *router* contract — status codes,
advisor-only gating, the draft-read gate on GET, and the 409 collapse for
``already_locked`` / ``already_approved``. Services are stubbed so the suite
stays hermetic and doesn't require Supabase to be running.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db import get_session
from app.main import app as fastapi_app
from app.models import Itinerary, ItineraryStatus
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    GraphView,
    ItineraryError,
    ItineraryOutcome,
)
from fastapi.testclient import TestClient

# ── Shared fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def advisor_sub() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def advisor_headers(make_token: Callable[..., str], advisor_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=advisor_sub)}"}


@pytest.fixture()
def client_sub() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def client_headers(make_token: Callable[..., str], client_sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=client_sub)}"}


def _new_itinerary(
    *,
    client_id: uuid.UUID | None = None,
    status: ItineraryStatus = ItineraryStatus.draft,
    locked_by: uuid.UUID | None = None,
    approved_by: uuid.UUID | None = None,
) -> Itinerary:
    return Itinerary(
        id=uuid.uuid4(),
        client_id=client_id,
        created_by=None,
        title="",
        locked_by=locked_by,
        locked_at=datetime.now(UTC) if locked_by else None,
        status=status,
        approved_by=approved_by,
        approved_at=datetime.now(UTC) if approved_by else None,
    )


@pytest.fixture()
def stub_routes(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Stub every S08 service entry point + ``_is_requester_advisor``.

    Each stub records its kwargs under ``calls[name]`` and returns whatever
    the test queued under ``returns[name]``. The session dependency is also
    overridden so no DB is needed.
    """
    from app.routers import itineraries as routers_itineraries

    calls: dict[str, list[dict[str, Any]]] = {
        "acquire_lock": [],
        "release_lock": [],
        "approve_itinerary": [],
        "assemble_initial_draft": [],
        "drain_queue": [],
        "get_itinerary_graph": [],
        "is_requester_advisor": [],
    }
    returns: dict[str, Any] = {}

    async def _acquire(_s: Any, actor: ActorContext, **kw: Any) -> Any:
        calls["acquire_lock"].append({"actor": actor, **kw})
        return returns["acquire_lock"]

    async def _release(_s: Any, actor: ActorContext, **kw: Any) -> Any:
        calls["release_lock"].append({"actor": actor, **kw})
        return returns["release_lock"]

    async def _approve(_s: Any, actor: ActorContext, **kw: Any) -> Any:
        calls["approve_itinerary"].append({"actor": actor, **kw})
        return returns["approve_itinerary"]

    async def _assemble(_s: Any, actor: ActorContext, **kw: Any) -> Any:
        calls["assemble_initial_draft"].append({"actor": actor, **kw})
        return returns["assemble_initial_draft"]

    async def _drain(_maker: Any, itinerary_id: uuid.UUID) -> int:
        calls["drain_queue"].append({"itinerary_id": itinerary_id})
        return returns.get("drain_queue", 0)

    async def _graph(_s: Any, itinerary_id: uuid.UUID) -> Any:
        calls["get_itinerary_graph"].append({"itinerary_id": itinerary_id})
        return returns["get_itinerary_graph"]

    async def _is_advisor(_s: Any, user_uuid: uuid.UUID | None) -> bool:
        calls["is_requester_advisor"].append({"user_uuid": user_uuid})
        return bool(returns.get("is_requester_advisor", False))

    async def _resolve_auth(_s: Any, client_id: uuid.UUID) -> uuid.UUID | None:
        calls.setdefault("resolve_client_auth_user_id", []).append({"client_id": client_id})
        return returns.get("resolve_client_auth_user_id")

    monkeypatch.setattr(routers_itineraries, "acquire_lock", _acquire)
    monkeypatch.setattr(routers_itineraries, "release_lock", _release)
    monkeypatch.setattr(routers_itineraries, "approve_itinerary", _approve)
    monkeypatch.setattr(routers_itineraries, "assemble_initial_draft", _assemble)
    monkeypatch.setattr(routers_itineraries, "drain_queue", _drain)
    monkeypatch.setattr(routers_itineraries, "get_itinerary_graph", _graph)
    monkeypatch.setattr(routers_itineraries, "_is_requester_advisor", _is_advisor)
    monkeypatch.setattr(routers_itineraries, "_resolve_client_auth_user_id", _resolve_auth)

    # GET resolves the caller's own open fork with a real query — stub it here so
    # these DB-less router tests don't touch the placeholder session.
    async def _no_open_fork(_session: object, _user: object, *, baseline_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(routers_itineraries, "_resolve_viewer_open_fork_id", _no_open_fork)

    # GET also sums per-currency totals (ADV-10) with a real query — stub it so
    # the DB-less router tests stay hermetic; default {} unless a test overrides.
    async def _sum_costs(_s: Any, _itinerary_id: uuid.UUID, **_kwargs: Any) -> Any:
        return returns.get("totals", {})

    monkeypatch.setattr(routers_itineraries, "sum_node_costs", _sum_costs)

    async def _session_dep() -> Iterator[object]:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _session_dep

    try:
        yield {
            "calls": calls,
            "returns": returns,
        }
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def as_advisor() -> Iterator[None]:
    """Make ``require_advisor`` pass for any authenticated user in the test.

    We swap ``require_advisor`` for ``require_user`` so the profiles lookup
    is skipped but the JWT principal still reaches the handler.
    """
    from app.auth import require_user
    from app.auth_guards import require_advisor

    fastapi_app.dependency_overrides[require_advisor] = require_user
    try:
        yield
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def as_non_advisor() -> Iterator[None]:
    """Make ``require_advisor`` 403 with ``advisor_only``."""
    from app.auth_guards import require_advisor
    from fastapi import HTTPException

    async def _reject() -> Any:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _reject
    try:
        yield
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


# ── POST /itinerary/{id}/lock ──────────────────────────────────────────────


def test_lock_requires_jwt(client: TestClient, stub_routes: dict[str, Any]) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/lock")
    assert resp.status_code == 401


def test_lock_non_advisor_gets_403(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_non_advisor: None,
) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/lock", headers=advisor_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "advisor_only"


def test_lock_happy_path_200(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    advisor_sub: str,
    as_advisor: None,
) -> None:
    iid = uuid.uuid4()
    locked = _new_itinerary(locked_by=uuid.UUID(advisor_sub))
    locked.id = iid
    stub_routes["returns"]["acquire_lock"] = locked

    resp = client.post(f"/itinerary/{iid}/lock", headers=advisor_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(iid)
    # Router should have stamped kind=ADVISOR on the service actor.
    call = stub_routes["calls"]["acquire_lock"][0]
    assert call["actor"].kind is ActorKind.ADVISOR
    assert call["itinerary_id"] == iid


def test_lock_already_locked_409(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_advisor: None,
) -> None:
    stub_routes["returns"]["acquire_lock"] = ItineraryError(
        outcome=ItineraryOutcome.LOCKED, detail="already_locked"
    )
    resp = client.post(f"/itinerary/{uuid.uuid4()}/lock", headers=advisor_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "already_locked"


def test_lock_not_found_404(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_advisor: None,
) -> None:
    stub_routes["returns"]["acquire_lock"] = ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    resp = client.post(f"/itinerary/{uuid.uuid4()}/lock", headers=advisor_headers)
    assert resp.status_code == 404


# ── POST /itinerary/{id}/release ───────────────────────────────────────────


def test_release_happy_path_drains_and_returns_count(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_advisor: None,
) -> None:
    iid = uuid.uuid4()
    released = _new_itinerary()
    released.id = iid
    stub_routes["returns"]["release_lock"] = released
    stub_routes["returns"]["drain_queue"] = 3

    resp = client.post(f"/itinerary/{iid}/release", headers=advisor_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["itinerary"]["id"] == str(iid)
    assert body["replayed_count"] == 3
    # drain_queue fired with the same id
    assert stub_routes["calls"]["drain_queue"][0]["itinerary_id"] == iid


def test_release_non_advisor_gets_403(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_non_advisor: None,
) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/release", headers=advisor_headers)
    assert resp.status_code == 403


# ── POST /itinerary/{id}/approve ───────────────────────────────────────────


def test_approve_happy_path_200(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    advisor_sub: str,
    as_advisor: None,
) -> None:
    iid = uuid.uuid4()
    approved = _new_itinerary(
        status=ItineraryStatus.approved,
        approved_by=uuid.UUID(advisor_sub),
    )
    approved.id = iid
    stub_routes["returns"]["approve_itinerary"] = approved

    resp = client.post(f"/itinerary/{iid}/approve", headers=advisor_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"


def test_approve_already_approved_409(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_advisor: None,
) -> None:
    stub_routes["returns"]["approve_itinerary"] = ItineraryError(
        outcome=ItineraryOutcome.VALIDATION_ERROR,
        detail="already_approved",
    )
    resp = client.post(f"/itinerary/{uuid.uuid4()}/approve", headers=advisor_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "already_approved"


def test_approve_non_advisor_gets_403(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
    as_non_advisor: None,
) -> None:
    resp = client.post(f"/itinerary/{uuid.uuid4()}/approve", headers=advisor_headers)
    assert resp.status_code == 403


# ── POST /itinerary/{id}/assemble ──────────────────────────────────────────


def _graph_view_for(iid: uuid.UUID, status: ItineraryStatus) -> GraphView:
    return GraphView(
        itinerary=Itinerary(id=iid, title="", client_id=None, created_by=None, status=status),
        nodes=[],
        edges=[],
    )


def test_assemble_happy_path_advisor(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    stub_routes["returns"]["is_requester_advisor"] = True
    stub_routes["returns"]["assemble_initial_draft"] = _graph_view_for(iid, ItineraryStatus.draft)
    resp = client.post(
        f"/itinerary/{iid}/assemble",
        headers=advisor_headers,
        json={
            "day_plan": [
                {
                    "day_index": 0,
                    "node_ids_in_order": [
                        str(uuid.uuid4()),
                        str(uuid.uuid4()),
                    ],
                }
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["itinerary"]["id"] == str(iid)
    # Service was called with ADVISOR actor because _is_requester_advisor
    # returned True for the requesting sub.
    call = stub_routes["calls"]["assemble_initial_draft"][0]
    assert call["actor"].kind is ActorKind.ADVISOR


def test_assemble_as_regular_user_stamps_user_actor(
    client: TestClient,
    stub_routes: dict[str, Any],
    client_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    stub_routes["returns"]["is_requester_advisor"] = False
    stub_routes["returns"]["assemble_initial_draft"] = _graph_view_for(iid, ItineraryStatus.draft)
    resp = client.post(
        f"/itinerary/{iid}/assemble",
        headers=client_headers,
        json={"day_plan": []},
    )
    assert resp.status_code == 200
    call = stub_routes["calls"]["assemble_initial_draft"][0]
    assert call["actor"].kind is ActorKind.USER


def test_assemble_locked_is_409(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
) -> None:
    stub_routes["returns"]["is_requester_advisor"] = False
    stub_routes["returns"]["assemble_initial_draft"] = ItineraryError(
        outcome=ItineraryOutcome.LOCKED, detail="already_locked"
    )
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/assemble",
        headers=advisor_headers,
        json={"day_plan": []},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "already_locked"


def test_assemble_validation_error_400(
    client: TestClient,
    stub_routes: dict[str, Any],
    advisor_headers: dict[str, str],
) -> None:
    stub_routes["returns"]["is_requester_advisor"] = False
    stub_routes["returns"]["assemble_initial_draft"] = ItineraryError(
        outcome=ItineraryOutcome.VALIDATION_ERROR,
        detail="node_not_in_itinerary",
    )
    resp = client.post(
        f"/itinerary/{uuid.uuid4()}/assemble",
        headers=advisor_headers,
        json={"day_plan": []},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "node_not_in_itinerary"


# ── Draft-read gate on GET /itinerary/{id} ────────────────────────────────


def _graph_with_client(
    iid: uuid.UUID,
    *,
    client_id: uuid.UUID | None,
    status: ItineraryStatus,
) -> GraphView:
    return GraphView(
        itinerary=Itinerary(
            id=iid,
            title="",
            client_id=client_id,
            created_by=None,
            status=status,
        ),
        nodes=[],
        edges=[],
    )


def test_get_draft_as_owning_client_200(
    client: TestClient,
    stub_routes: dict[str, Any],
    make_token: Callable[..., str],
) -> None:
    # clients.id and auth.users.id live in different UUID namespaces, so
    # the test distinguishes them. The owning-client path passes when
    # ``_resolve_client_auth_user_id(client_id)`` returns the caller's sub.
    client_row_id = uuid.uuid4()
    caller_auth_user_id = uuid.uuid4()
    iid = uuid.uuid4()
    stub_routes["returns"]["get_itinerary_graph"] = _graph_with_client(
        iid, client_id=client_row_id, status=ItineraryStatus.draft
    )
    stub_routes["returns"]["resolve_client_auth_user_id"] = caller_auth_user_id
    headers = {"Authorization": f"Bearer {make_token(sub=str(caller_auth_user_id))}"}
    resp = client.get(f"/itinerary/{iid}", headers=headers)
    assert resp.status_code == 200
    # No advisor lookup needed — we matched on owning client path.
    assert stub_routes["calls"]["is_requester_advisor"] == []


def test_get_draft_as_non_owning_non_advisor_403(
    client: TestClient,
    stub_routes: dict[str, Any],
    make_token: Callable[..., str],
) -> None:
    client_row_id = uuid.uuid4()
    caller_auth_user_id = uuid.uuid4()
    different_auth_user_id = uuid.uuid4()
    iid = uuid.uuid4()
    stub_routes["returns"]["get_itinerary_graph"] = _graph_with_client(
        iid, client_id=client_row_id, status=ItineraryStatus.draft
    )
    # The clients row's auth_user_id is some OTHER user, not our caller.
    stub_routes["returns"]["resolve_client_auth_user_id"] = different_auth_user_id
    stub_routes["returns"]["is_requester_advisor"] = False
    headers = {"Authorization": f"Bearer {make_token(sub=str(caller_auth_user_id))}"}
    resp = client.get(f"/itinerary/{iid}", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"


def test_get_draft_as_advisor_200(
    client: TestClient,
    stub_routes: dict[str, Any],
    make_token: Callable[..., str],
) -> None:
    client_row_id = uuid.uuid4()
    advisor_id = uuid.uuid4()
    iid = uuid.uuid4()
    stub_routes["returns"]["get_itinerary_graph"] = _graph_with_client(
        iid, client_id=client_row_id, status=ItineraryStatus.draft
    )
    # Advisor isn't the owning client — owner lookup returns None / mismatch.
    stub_routes["returns"]["resolve_client_auth_user_id"] = None
    stub_routes["returns"]["is_requester_advisor"] = True
    headers = {"Authorization": f"Bearer {make_token(sub=str(advisor_id))}"}
    resp = client.get(f"/itinerary/{iid}", headers=headers)
    assert resp.status_code == 200


def test_get_approved_as_non_owning_user_200(
    client: TestClient,
    stub_routes: dict[str, Any],
    make_token: Callable[..., str],
) -> None:
    # Once status=approved, the draft gate is bypassed — any authenticated
    # caller reads (broader ACLs are out of S08 scope).
    owner_id = uuid.uuid4()
    iid = uuid.uuid4()
    stub_routes["returns"]["get_itinerary_graph"] = _graph_with_client(
        iid, client_id=owner_id, status=ItineraryStatus.approved
    )
    headers = {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}
    resp = client.get(f"/itinerary/{iid}", headers=headers)
    assert resp.status_code == 200
    # No advisor lookup fired — the gate only runs on status=draft.
    assert stub_routes["calls"]["is_requester_advisor"] == []
