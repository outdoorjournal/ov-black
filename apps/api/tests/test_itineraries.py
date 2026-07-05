"""Coverage for the itinerary graph surface (M001/S02 T05).

Two layers:

1. Router tests — exercise the HTTP contract with the service dependency
   overridden. We care here about outcome-to-status mapping, JWT
   enforcement, and payload validation (Pydantic 422s).
2. Service + integration tests — exercise the real service against a
   locally-running Supabase Postgres so same-transaction history writes,
   the recursive CTE assembly, and the schema-level constraints
   (provenance, self-loop) are all covered end-to-end. Gated on
   ``_supabase_running()`` so a fresh checkout without Docker skips cleanly.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from app.db import get_session
from app.main import app as fastapi_app
from app.models import (
    CostKind,
    Edge,
    EdgeHistory,
    EdgeType,
    Itinerary,
    ItineraryTimingKind,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
)
from app.routers.itineraries import UpdateItineraryRequest, _itinerary_to_response
from app.services.itineraries import (
    ActorContext,
    ActorKind,
    ItineraryError,
    ItineraryOutcome,
    _check_provenance,
    _serialize_starts_at,
    add_edge,
    add_node,
    create_itinerary,
    delete_edge,
    delete_node,
    get_itinerary_graph,
    update_itinerary_details,
    update_node,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


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


# ── Pure unit tests: provenance gate ───────────────────────────────────────


def test_check_provenance_accepts_both_set() -> None:
    assert _check_provenance("ov", "trip-123") is None


def test_check_provenance_accepts_both_unset() -> None:
    assert _check_provenance(None, None) is None


def test_check_provenance_rejects_source_without_id() -> None:
    err = _check_provenance("ov", None)
    assert err is not None
    assert err.outcome is ItineraryOutcome.INVALID_PROVENANCE


def test_check_provenance_rejects_id_without_source() -> None:
    err = _check_provenance(None, "trip-123")
    assert err is not None
    assert err.outcome is ItineraryOutcome.INVALID_PROVENANCE


# ── Pure unit tests: starts_at serialization ───────────────────────────────


class _FakeRange:
    """Stand-in for the asyncpg Range object the driver returns."""

    def __init__(self, lower: datetime | None, upper: datetime | None) -> None:
        self.lower = lower
        self.upper = upper


def test_serialize_starts_at_none_yields_none() -> None:
    assert _serialize_starts_at(None) == (None, None)


def test_serialize_starts_at_range_object() -> None:
    jst = timezone(timedelta(hours=9))
    lower = datetime(2024, 6, 20, 16, 10, tzinfo=jst)
    upper = datetime(2024, 6, 20, 16, 40, tzinfo=jst)
    iso, duration = _serialize_starts_at(_FakeRange(lower, upper))
    assert iso == "2024-06-20T16:10:00+09:00"
    assert duration == 30


def test_serialize_starts_at_range_without_upper() -> None:
    jst = timezone(timedelta(hours=9))
    lower = datetime(2024, 6, 20, 16, 10, tzinfo=jst)
    iso, duration = _serialize_starts_at(_FakeRange(lower, None))
    assert iso == "2024-06-20T16:10:00+09:00"
    assert duration is None


def test_serialize_starts_at_string_literal() -> None:
    """The Postgres text form (in case a raw CTE column surfaces it)."""
    literal = '["2024-06-20 16:10:00+09","2024-06-20 16:40:00+09")'
    iso, duration = _serialize_starts_at(literal)
    assert iso == "2024-06-20T16:10:00+09:00"
    assert duration == 30


def test_serialize_starts_at_string_unbounded_upper() -> None:
    literal = '["2024-06-20 16:10:00+09",)'
    iso, duration = _serialize_starts_at(literal)
    assert iso == "2024-06-20T16:10:00+09:00"
    assert duration is None


def test_serialize_starts_at_applies_tz_offset_minutes() -> None:
    """A UTC-stored instant (as a CTE column surfaces it) is re-emitted in the
    node's local offset when tz_offset_minutes is supplied, same instant.
    """
    utc = UTC
    # 07:10Z is the UTC normalization of JST 16:10 — what the tstzrange stores.
    lower = datetime(2024, 6, 20, 7, 10, tzinfo=utc)
    upper = datetime(2024, 6, 20, 7, 40, tzinfo=utc)
    iso, duration = _serialize_starts_at(_FakeRange(lower, upper), 540)
    assert iso == "2024-06-20T16:10:00+09:00"
    assert iso.endswith("+09:00")
    assert datetime.fromisoformat(iso) == lower  # same instant
    assert duration == 30


def test_serialize_starts_at_none_offset_keeps_utc() -> None:
    """No tz_offset_minutes → the lower bound's own (UTC) offset is kept."""
    utc = UTC
    lower = datetime(2024, 6, 20, 7, 10, tzinfo=utc)
    iso, _ = _serialize_starts_at(_FakeRange(lower, None), None)
    assert iso == "2024-06-20T07:10:00+00:00"


# ── Router tests (service stubbed, JWT real) ───────────────────────────────


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    """Mint a valid JWT for router tests that require auth."""
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


@pytest.fixture()
def stub_service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace every service function with a deterministic fake.

    Stored call args + configurable return values so tests can assert the
    router forwards inputs correctly and maps outcomes to the right status.
    """
    calls: dict[str, list[dict[str, Any]]] = {
        "create_itinerary": [],
        "get_itinerary_graph": [],
        "update_itinerary_details": [],
        "add_node": [],
        "update_node": [],
        "delete_node": [],
        "add_edge": [],
        "delete_edge": [],
    }
    returns: dict[str, Any] = {}

    async def _create(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["create_itinerary"].append({"actor": actor, **kwargs})
        return returns.get("create_itinerary") or Itinerary(
            id=uuid.uuid4(),
            title=kwargs.get("title", ""),
            client_id=kwargs.get("client_id"),
            created_by=actor.user_id,
            brief=kwargs.get("brief"),
            timing_kind=kwargs.get("timing_kind"),
            date_start=kwargs.get("date_start"),
            date_end=kwargs.get("date_end"),
            duration_nights=kwargs.get("duration_nights"),
            timing_note=kwargs.get("timing_note"),
        )

    async def _update_itinerary(
        _session: Any, actor: ActorContext, _itinerary: Any, *, fields: dict[str, Any]
    ) -> Any:
        calls["update_itinerary_details"].append({"actor": actor, "fields": fields})
        if "update_itinerary_details" in returns:
            return returns["update_itinerary_details"]
        # Echo the applied fields back on a fresh row so the response serializes.
        return Itinerary(
            id=uuid.uuid4(),
            title=fields.get("title", ""),
            brief=fields.get("brief"),
            timing_kind=fields.get("timing_kind"),
            date_start=fields.get("date_start"),
            date_end=fields.get("date_end"),
            duration_nights=fields.get("duration_nights"),
            timing_note=fields.get("timing_note"),
        )

    async def _get_graph(_session: Any, itinerary_id: uuid.UUID) -> Any:
        calls["get_itinerary_graph"].append({"itinerary_id": itinerary_id})
        return returns.get(
            "get_itinerary_graph", ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
        )

    async def _add_node(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["add_node"].append({"actor": actor, **kwargs})
        if "add_node" in returns:
            return returns["add_node"]
        return Node(
            id=uuid.uuid4(),
            itinerary_id=kwargs["itinerary_id"],
            parent_subgraph_id=kwargs.get("parent_subgraph_id"),
            type=kwargs["type"],
            status=kwargs.get("status", NodeStatus.idea),
            title=kwargs.get("title", ""),
            source=kwargs.get("source"),
            source_id=kwargs.get("source_id"),
            metadata_=kwargs.get("metadata") or {},
        )

    async def _update_node(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["update_node"].append({"actor": actor, **kwargs})
        if "update_node" in returns:
            return returns["update_node"]
        return Node(
            id=kwargs["node_id"],
            itinerary_id=kwargs["itinerary_id"],
            parent_subgraph_id=None,
            type=NodeType.experience,
            status=NodeStatus.idea,
            title=kwargs.get("title", ""),
            source=None,
            source_id=None,
            metadata_={},
        )

    async def _delete_node(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["delete_node"].append({"actor": actor, **kwargs})
        return returns.get("delete_node")  # None = success by default

    async def _add_edge(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["add_edge"].append({"actor": actor, **kwargs})
        if "add_edge" in returns:
            return returns["add_edge"]
        return Edge(
            id=uuid.uuid4(),
            itinerary_id=kwargs["itinerary_id"],
            from_node_id=kwargs["from_node_id"],
            to_node_id=kwargs["to_node_id"],
            type=kwargs["type"],
            metadata_=kwargs.get("metadata") or {},
        )

    async def _delete_edge(_session: Any, actor: ActorContext, **kwargs: Any) -> Any:
        calls["delete_edge"].append({"actor": actor, **kwargs})
        return returns.get("delete_edge")

    # The PATCH/DELETE node endpoints resolve advisor-ness (G1) to stamp the
    # actor kind. Stub it off the fake session; defaults to non-advisor so the
    # existing USER-actor expectations hold. Flip via returns["is_advisor"].
    async def _is_advisor(_session: Any, user_uuid: uuid.UUID | None) -> bool:
        return bool(returns.get("is_advisor", False))

    # The graph-read endpoint sums per-currency totals (ADV-10). Stub it off the
    # fake session — hermetic like the rest — returning {} unless a test sets
    # returns["totals"] to assert the price surfaces on the response.
    async def _sum_costs(_session: Any, _itinerary_id: uuid.UUID, **_kwargs: Any) -> Any:
        return returns.get("totals", {})

    # Patch the bound names inside the router module — that's the call site.
    from app.routers import itineraries as routers_itineraries

    monkeypatch.setattr(routers_itineraries, "create_itinerary", _create)
    monkeypatch.setattr(routers_itineraries, "get_itinerary_graph", _get_graph)
    monkeypatch.setattr(routers_itineraries, "sum_node_costs", _sum_costs)
    monkeypatch.setattr(routers_itineraries, "update_itinerary_details", _update_itinerary)
    monkeypatch.setattr(routers_itineraries, "add_node", _add_node)
    monkeypatch.setattr(routers_itineraries, "update_node", _update_node)
    monkeypatch.setattr(routers_itineraries, "delete_node", _delete_node)
    monkeypatch.setattr(routers_itineraries, "add_edge", _add_edge)
    monkeypatch.setattr(routers_itineraries, "delete_edge", _delete_edge)
    monkeypatch.setattr(routers_itineraries, "_is_requester_advisor", _is_advisor)

    # The node/edge write endpoints pre-load the itinerary and gate it with
    # ``assert_itinerary_writable`` (owner/advisor). These route-unit tests stub
    # the DB, so short-circuit both: load returns a non-None placeholder (skip
    # the 404 branch) and the writable gate is a no-op (authorized). Authz is
    # exercised separately against a real session in test_itinerary_writable.py.
    async def _load(_session: Any, itinerary_id: uuid.UUID) -> Any:
        return object()

    async def _writable(_session: Any, _user: Any, _itinerary: Any) -> None:
        return None

    monkeypatch.setattr(routers_itineraries, "_load_itinerary", _load)
    monkeypatch.setattr(routers_itineraries, "assert_itinerary_writable", _writable)

    # GET resolves the caller's own open fork ("My version") with a real query —
    # stub it for these DB-less router-contract tests (exercised against a live
    # session in test_fork_reconcile.py::test_resolve_viewer_open_fork_id).
    async def _no_open_fork(_session: Any, _user: Any, *, baseline_id: uuid.UUID) -> Any:
        return None

    monkeypatch.setattr(routers_itineraries, "_resolve_viewer_open_fork_id", _no_open_fork)

    # Also override the session dependency so no DB is required.
    async def _dep() -> Iterator[object]:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        yield {"calls": calls, "returns": returns}
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


def test_create_itinerary_requires_jwt(client: TestClient, stub_service: dict[str, Any]) -> None:
    resp = client.post("/itinerary", json={"title": "Como"})
    assert resp.status_code == 401


def test_create_itinerary_returns_201_and_forwards_actor(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
    make_token: Callable[..., str],
) -> None:
    sub = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {make_token(sub=sub)}"}
    resp = client.post("/itinerary", json={"title": "Como"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Como"
    assert uuid.UUID(body["id"])
    assert stub_service["calls"]["create_itinerary"][0]["actor"].kind is ActorKind.USER
    assert stub_service["calls"]["create_itinerary"][0]["actor"].user_id == uuid.UUID(sub)


def test_create_itinerary_with_non_uuid_sub_still_succeeds(
    client: TestClient,
    stub_service: dict[str, Any],
    make_token: Callable[..., str],
) -> None:
    # Some Supabase user ids may not be UUIDs in dev; the router must not 500
    # — it records the string in actor_id and leaves user_id NULL.
    headers = {"Authorization": f"Bearer {make_token(sub='not-a-uuid')}"}
    resp = client.post("/itinerary", json={"title": "Como"}, headers=headers)
    assert resp.status_code == 201
    actor = stub_service["calls"]["create_itinerary"][0]["actor"]
    assert actor.user_id is None
    assert actor.actor_id == "not-a-uuid"


# ── Trip brief + timing (0033) — router contract ───────────────────────────


def test_create_itinerary_forwards_brief_and_timing(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        "/itinerary",
        json={
            "title": "Greece",
            "brief": "Sailing in Greece with my family",
            "timing_kind": "window",
            "date_start": "2027-06-01",
            "date_end": "2027-08-31",
            "duration_nights": 7,
            "timing_note": "can't go in August; back by a Sunday",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["brief"] == "Sailing in Greece with my family"
    assert body["timing_kind"] == "window"
    assert body["date_start"] == "2027-06-01"
    assert body["duration_nights"] == 7
    # Fields reach the service verbatim.
    fwd = stub_service["calls"]["create_itinerary"][0]
    assert fwd["brief"] == "Sailing in Greece with my family"
    assert fwd["timing_kind"] is ItineraryTimingKind.window
    assert fwd["duration_nights"] == 7


def test_update_itinerary_forwards_fields_and_returns_200(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}",
        json={
            "brief": "A week diving in the Red Sea",
            "timing_kind": "exact",
            "date_start": "2027-03-18",
            "date_end": "2027-03-25",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["brief"] == "A week diving in the Red Sea"
    assert body["timing_kind"] == "exact"
    assert body["date_end"] == "2027-03-25"
    # Only the fields actually sent are forwarded (partial semantics).
    fields = stub_service["calls"]["update_itinerary_details"][0]["fields"]
    assert set(fields) == {"brief", "timing_kind", "date_start", "date_end"}
    assert "duration_nights" not in fields


def test_update_itinerary_explicit_null_clears_date(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    # Switching from exact dates to a flexible window: an explicit null must
    # reach the service as a present field (so it clears), not be dropped.
    iid = uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}",
        json={"timing_kind": "flexible", "date_start": None, "date_end": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    fields = stub_service["calls"]["update_itinerary_details"][0]["fields"]
    assert fields["date_start"] is None
    assert "date_start" in fields and "date_end" in fields


def test_update_itinerary_rejects_zero_duration(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = client.patch(
        f"/itinerary/{uuid.uuid4()}",
        json={"duration_nights": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_update_itinerary_rejects_unknown_field(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = client.patch(
        f"/itinerary/{uuid.uuid4()}",
        json={"destination": "Greece"},  # not a real field
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_update_itinerary_requires_jwt(client: TestClient, stub_service: dict[str, Any]) -> None:
    resp = client.patch(f"/itinerary/{uuid.uuid4()}", json={"brief": "x"})
    assert resp.status_code == 401


def test_update_request_exclude_unset_distinguishes_omitted_from_null() -> None:
    """The partial-PATCH contract the intake depends on, at the Pydantic layer."""
    only_brief = UpdateItineraryRequest(brief="x").model_dump(exclude_unset=True)
    assert only_brief == {"brief": "x"}

    explicit_null = UpdateItineraryRequest(date_start=None).model_dump(exclude_unset=True)
    assert "date_start" in explicit_null  # sent-as-null is "set", clears the value

    empty = UpdateItineraryRequest().model_dump(exclude_unset=True)
    assert empty == {}


def test_get_itinerary_not_found_is_404(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    resp = client.get(f"/itinerary/{iid}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "not_found"


def test_get_itinerary_assembles_graph(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    from app.services.itineraries import EdgeOut, GraphView, NodeOut

    iid = uuid.uuid4()
    root_id, child_id, alt_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stub_service["returns"]["get_itinerary_graph"] = GraphView(
        itinerary=Itinerary(id=iid, title="Como"),
        nodes=[
            NodeOut(
                id=root_id,
                itinerary_id=iid,
                parent_subgraph_id=None,
                type=NodeType.experience,
                status=NodeStatus.proposed,
                title="Root",
                source="ov",
                source_id="t-1",
                metadata={},
                cost_amount=Decimal("1200.00"),
                cost_currency="USD",
                cost_kind=CostKind.per_person,
                starts_at="2024-06-20T16:10:00+09:00",
                duration_minutes=30,
                depth=0,
            ),
            NodeOut(
                id=child_id,
                itinerary_id=iid,
                parent_subgraph_id=root_id,
                type=NodeType.meal,
                status=NodeStatus.idea,
                title="Child",
                source=None,
                source_id=None,
                metadata={},
                cost_amount=None,
                cost_currency=None,
                cost_kind=None,
                starts_at=None,
                duration_minutes=None,
                depth=1,
            ),
        ],
        edges=[
            EdgeOut(
                id=uuid.uuid4(),
                itinerary_id=iid,
                from_node_id=child_id,
                to_node_id=alt_id,
                type=EdgeType.alternative_to,
                metadata={},
            ),
        ],
    )
    resp = client.get(f"/itinerary/{iid}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["itinerary"]["title"] == "Como"
    assert len(body["nodes"]) == 2
    assert body["nodes"][0]["depth"] == 0
    assert body["nodes"][1]["depth"] == 1
    # Scheduled timing is serialized through onto the response.
    assert body["nodes"][0]["starts_at"] == "2024-06-20T16:10:00+09:00"
    assert body["nodes"][0]["duration_minutes"] == 30
    assert body["nodes"][1]["starts_at"] is None
    assert body["nodes"][1]["duration_minutes"] is None
    # First-class cost is serialized through the graph-read path (B4).
    assert body["nodes"][0]["cost_amount"] == "1200.00"
    assert body["nodes"][0]["cost_currency"] == "USD"
    assert body["nodes"][0]["cost_kind"] == "per_person"
    assert body["nodes"][1]["cost_amount"] is None
    assert len(body["edges"]) == 1
    assert body["edges"][0]["type"] == "alternative_to"
    # Totals default to empty when nothing is priced (ADV-10).
    assert body["totals"] == {}


def test_get_itinerary_surfaces_per_currency_totals(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """The graph read surfaces the plan's per-currency price (ADV-10) so the UI
    can show a total beside the one-action approve. Decimal → str like cost."""
    from app.services.itineraries import GraphView

    iid = uuid.uuid4()
    stub_service["returns"]["get_itinerary_graph"] = GraphView(
        itinerary=Itinerary(id=iid, title="Kyoto"),
        nodes=[],
        edges=[],
    )
    stub_service["returns"]["totals"] = {
        "USD": Decimal("450.00"),
        "EUR": Decimal("80.00"),
    }
    resp = client.get(f"/itinerary/{iid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["totals"] == {"USD": "450.00", "EUR": "80.00"}


def test_add_node_provenance_asymmetry_returns_400(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["returns"]["add_node"] = ItineraryError(
        outcome=ItineraryOutcome.INVALID_PROVENANCE,
        detail="source and source_id must be provided together",
    )
    iid = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{iid}/nodes",
        json={"type": "experience", "source": "ov"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "source_id" in resp.json()["detail"]


def test_add_node_invalid_parent_returns_400(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["returns"]["add_node"] = ItineraryError(
        outcome=ItineraryOutcome.INVALID_PARENT,
        detail="parent_subgraph_id does not belong to this itinerary",
    )
    iid = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{iid}/nodes",
        json={
            "type": "note",
            "parent_subgraph_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("parent_subgraph_id")


def test_add_node_self_loop_style_validation_returns_400(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    # Service returns a DB-sourced validation error (e.g. edges_no_self_loop
    # bubbling up) — the router must not 500.
    stub_service["returns"]["add_edge"] = ItineraryError(
        outcome=ItineraryOutcome.VALIDATION_ERROR,
        detail="edges_no_self_loop",
    )
    iid = uuid.uuid4()
    same = str(uuid.uuid4())
    resp = client.post(
        f"/itinerary/{iid}/edges",
        json={
            "from_node_id": same,
            "to_node_id": same,
            "type": "follows",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "edges_no_self_loop"


def test_create_node_invalid_type_returns_422(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{iid}/nodes",
        json={"type": "not_a_valid_type"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_update_node_forbids_unknown_fields(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}/nodes/{nid}",
        json={"itinerary_id": str(uuid.uuid4())},  # not in whitelist
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_patch_node_forwards_cost_fields(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """B4: the advisor PATCH surface forwards first-class cost to update_node."""
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}/nodes/{nid}",
        json={"cost_amount": "1234.50", "cost_currency": "USD", "cost_kind": "total"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    call = stub_service["calls"]["update_node"][-1]
    assert call["cost_amount"] == Decimal("1234.50")
    assert call["cost_currency"] == "USD"
    assert call["cost_kind"] is CostKind.total


def test_patch_node_conflict_maps_to_409(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """A CONFLICT outcome (M005 money gate) must map to 409, never fall through to 500.

    Regression: ``ItineraryOutcome.CONFLICT`` (e.g. the ``use_booking_flow`` refusal
    when a node is flipped straight to booked via update_node) was unmapped in
    ``_raise_for_error`` and surfaced as a 500 ``internal_error``.
    """
    stub_service["returns"]["update_node"] = ItineraryError(
        outcome=ItineraryOutcome.CONFLICT,
        detail="use_booking_flow",
    )
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}/nodes/{nid}",
        json={"status": "booked"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "use_booking_flow"


def test_raise_for_error_maps_every_outcome_below_500() -> None:
    """No error outcome may silently fall through to a 500 in the router mapping.

    ``_raise_for_error`` claims "every enum value is mapped above"; this pins that
    claim so a newly added ``ItineraryOutcome`` can't regress into ``internal_error``.
    """
    from app.routers.itineraries import _raise_for_error

    for outcome in ItineraryOutcome:
        if outcome is ItineraryOutcome.OK:
            continue  # not an error envelope
        with pytest.raises(HTTPException) as exc:
            _raise_for_error(ItineraryError(outcome=outcome, detail="x"))
        status = exc.value.status_code
        assert status < 500, f"{outcome.value} fell through to {status}"


def test_create_node_forwards_cost_fields(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """A hand-built node can carry cost too (advisor authoring, B7)."""
    iid = uuid.uuid4()
    resp = client.post(
        f"/itinerary/{iid}/nodes",
        json={
            "type": "experience",
            "cost_amount": "300.00",
            "cost_currency": "USD",
            "cost_kind": "per_person",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    call = stub_service["calls"]["add_node"][-1]
    assert call["cost_amount"] == Decimal("300.00")
    assert call["cost_currency"] == "USD"
    assert call["cost_kind"] is CostKind.per_person


def test_delete_node_returns_204(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.delete(f"/itinerary/{iid}/nodes/{nid}", headers=auth_headers)
    assert resp.status_code == 204
    assert resp.content == b""


def test_delete_node_not_found_returns_404(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["returns"]["delete_node"] = ItineraryError(outcome=ItineraryOutcome.NOT_FOUND)
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.delete(f"/itinerary/{iid}/nodes/{nid}", headers=auth_headers)
    assert resp.status_code == 404


# ── G1: status-gate actor resolution + outcome mapping + lock_reason ────────


def test_patch_node_stamps_advisor_when_role_advisor(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """An advisor caller is stamped ADVISOR so the service gate lets them demote."""
    stub_service["returns"]["is_advisor"] = True
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(
        f"/itinerary/{iid}/nodes/{nid}", json={"status": "proposed"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert stub_service["calls"]["update_node"][-1]["actor"].kind is ActorKind.ADVISOR


def test_patch_node_stamps_user_for_non_advisor(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """A traveler/agent caller stays USER — they can't move firmed nodes."""
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(f"/itinerary/{iid}/nodes/{nid}", json={"title": "x"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert stub_service["calls"]["update_node"][-1]["actor"].kind is ActorKind.USER


def test_delete_node_stamps_advisor_when_role_advisor(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["returns"]["is_advisor"] = True
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.delete(f"/itinerary/{iid}/nodes/{nid}", headers=auth_headers)
    assert resp.status_code == 204
    assert stub_service["calls"]["delete_node"][-1]["actor"].kind is ActorKind.ADVISOR


def test_patch_node_status_locked_maps_to_409(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    stub_service["returns"]["update_node"] = ItineraryError(
        outcome=ItineraryOutcome.STATUS_LOCKED, detail="status_locked"
    )
    iid, nid = uuid.uuid4(), uuid.uuid4()
    resp = client.patch(f"/itinerary/{iid}/nodes/{nid}", json={"title": "x"}, headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "status_locked"


def test_patch_node_response_carries_lock_reason(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """A booked node serialized back through the write path carries lock_reason."""
    iid, nid = uuid.uuid4(), uuid.uuid4()
    stub_service["returns"]["update_node"] = Node(
        id=nid,
        itinerary_id=iid,
        type=NodeType.hotel,
        status=NodeStatus.booked,
        title="Aman",
        metadata_={},
    )
    resp = client.patch(
        f"/itinerary/{iid}/nodes/{nid}", json={"title": "Aman"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lock_reason"] == "status_locked"


def test_graph_read_serializes_lock_reason(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    from app.services.itineraries import GraphView, NodeOut

    iid, firmed_id, free_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def _node_out(node_id: uuid.UUID, status: NodeStatus, lock_reason: str | None) -> Any:
        return NodeOut(
            id=node_id,
            itinerary_id=iid,
            parent_subgraph_id=None,
            type=NodeType.hotel,
            status=status,
            title="n",
            source=None,
            source_id=None,
            metadata={},
            cost_amount=None,
            cost_currency=None,
            cost_kind=None,
            starts_at=None,
            duration_minutes=None,
            depth=0,
            lock_reason=lock_reason,
        )

    stub_service["returns"]["get_itinerary_graph"] = GraphView(
        itinerary=Itinerary(id=iid, title="Como"),
        nodes=[
            _node_out(firmed_id, NodeStatus.booked, "status_locked"),
            _node_out(free_id, NodeStatus.proposed, None),
        ],
        edges=[],
    )
    resp = client.get(f"/itinerary/{iid}", headers=auth_headers)
    assert resp.status_code == 200
    by_id = {n["id"]: n for n in resp.json()["nodes"]}
    assert by_id[str(firmed_id)]["lock_reason"] == "status_locked"
    assert by_id[str(free_id)]["lock_reason"] is None


def test_create_edge_returns_201(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid = uuid.uuid4()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    resp = client.post(
        f"/itinerary/{iid}/edges",
        json={"from_node_id": a, "to_node_id": b, "type": "follows"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["from_node_id"] == a
    assert body["to_node_id"] == b
    assert body["type"] == "follows"


def test_delete_edge_returns_204(
    client: TestClient,
    stub_service: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    iid, eid = uuid.uuid4(), uuid.uuid4()
    resp = client.delete(f"/itinerary/{iid}/edges/{eid}", headers=auth_headers)
    assert resp.status_code == 204


def test_openapi_exposes_new_contract(client: TestClient) -> None:
    # Slice plan Inspection Surfaces: GET /openapi.json exposes the new
    # contract so packages/api-client regeneration is one command.
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/itinerary" in paths
    assert "/itinerary/{itinerary_id}" in paths
    assert "/itinerary/{itinerary_id}/nodes" in paths
    assert "/itinerary/{itinerary_id}/nodes/{node_id}" in paths
    assert "/itinerary/{itinerary_id}/edges" in paths
    assert "/itinerary/{itinerary_id}/edges/{edge_id}" in paths


def test_itinerary_routes_are_behind_jwt(client: TestClient) -> None:
    # Every route must require a JWT — the invariant is that nothing in
    # PUBLIC_PATHS references /itinerary.
    from app.auth import PUBLIC_PATHS

    for p in PUBLIC_PATHS:
        assert not p.startswith("/itinerary")


# ── Integration tests (against local Supabase Postgres) ─────────────────────


@pytest_asyncio.fixture()
async def db_session() -> AsyncSession:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


async def _cleanup(_session: AsyncSession, itinerary_id: uuid.UUID) -> None:
    """Teardown using a fresh engine so rollback-wrecked sessions don't leak.

    Running on a throwaway connection means an earlier integrity-error path
    (which rolls back the per-test session) can't break our cleanup DELETEs.
    """
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("delete from public.edge_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.node_history where itinerary_id = :i"),
                {"i": itinerary_id},
            )
            await conn.execute(
                text("delete from public.itineraries where id = :i"),
                {"i": itinerary_id},
            )
    finally:
        await engine.dispose()


def _actor() -> ActorContext:
    return ActorContext(user_id=None, kind=ActorKind.SYSTEM, actor_id="test-actor")


@integration
@pytest.mark.asyncio
async def test_create_itinerary_persists_row(db_session: AsyncSession) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="Como trip")
    try:
        assert itinerary.id is not None
        fetched = (
            await db_session.execute(select(Itinerary).where(Itinerary.id == itinerary.id))
        ).scalar_one()
        assert fetched.title == "Como trip"
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_create_itinerary_persists_brief_and_timing(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(
        db_session,
        _actor(),
        title="Greece",
        brief="Sailing in Greece with my family",
        timing_kind=ItineraryTimingKind.window,
        date_start=date(2027, 6, 1),
        date_end=date(2027, 8, 31),
        duration_nights=7,
        timing_note="can't go in August",
    )
    try:
        fetched = (
            await db_session.execute(select(Itinerary).where(Itinerary.id == itinerary.id))
        ).scalar_one()
        assert fetched.brief == "Sailing in Greece with my family"
        assert fetched.timing_kind is ItineraryTimingKind.window
        assert fetched.date_start == date(2027, 6, 1)
        assert fetched.date_end == date(2027, 8, 31)
        assert fetched.duration_nights == 7
        assert fetched.timing_note == "can't go in August"
        # The response serializer carries the fields through verbatim.
        resp = _itinerary_to_response(fetched)
        assert resp.brief == "Sailing in Greece with my family"
        assert resp.timing_kind is ItineraryTimingKind.window
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_update_itinerary_details_partial_then_clear(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="draft")
    try:
        # 1) Set the brief only — timing stays untouched (None).
        await update_itinerary_details(
            db_session, _actor(), itinerary, fields={"brief": "Ski week in the Alps"}
        )
        assert itinerary.brief == "Ski week in the Alps"
        assert itinerary.timing_kind is None

        # 2) Commit to exact dates.
        await update_itinerary_details(
            db_session,
            _actor(),
            itinerary,
            fields={
                "timing_kind": ItineraryTimingKind.exact,
                "date_start": date(2027, 1, 10),
                "date_end": date(2027, 1, 17),
            },
        )
        assert itinerary.timing_kind is ItineraryTimingKind.exact
        assert itinerary.date_start == date(2027, 1, 10)

        # 3) Clear the start via an explicit None; the end + brief stay put
        #    (omitted keys are untouched, an explicit null clears).
        await update_itinerary_details(db_session, _actor(), itinerary, fields={"date_start": None})
        assert itinerary.date_start is None
        assert itinerary.date_end == date(2027, 1, 17)
        assert itinerary.brief == "Ski week in the Alps"
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_update_itinerary_details_rejects_reversed_range(db_session: AsyncSession) -> None:
    itinerary = await create_itinerary(db_session, _actor(), title="draft")
    try:
        result = await update_itinerary_details(
            db_session,
            _actor(),
            itinerary,
            fields={"date_start": date(2027, 5, 10), "date_end": date(2027, 5, 1)},
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
        assert result.detail == "date_end_before_start"
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_add_node_writes_history_in_same_transaction(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="history test")
    try:
        node = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="Amalfi",
            source="ov",
            source_id="trip-42",
        )
        assert isinstance(node, Node)
        rows = (
            (await db_session.execute(select(NodeHistory).where(NodeHistory.node_id == node.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].op == "insert"
        assert rows[0].before is None
        assert rows[0].after is not None
        assert rows[0].after["title"] == "Amalfi"
        assert rows[0].actor_kind == "system"
        assert rows[0].actor_id == "test-actor"
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_add_node_persists_schedule_for_non_note(
    db_session: AsyncSession,
) -> None:
    """A non-note node (flight) keeps its starts_at + duration through the graph.

    Regression: add_node used to honor starts_at only for note nodes, so a
    flight/meal/experience landed with a NULL range and the timeline had to
    synthesize a placeholder slot. The offset (JST here) must survive the
    UTC tstzrange round-trip, and the wall-clock is mirrored into metadata.
    """
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="schedule test")
    try:
        node = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.flight,
            title="LAX → HND",
            starts_at="2026-07-29T21:40:00-07:00",
            duration_minutes=740,
        )
        assert isinstance(node, Node)
        # Mirrored back into metadata so the web timeline reads the local time.
        assert node.metadata_["start_time"] == "2026-07-29T21:40:00-07:00"
        assert node.metadata_["tz_offset_minutes"] == -420
        assert node.metadata_["duration_minutes"] == 740

        view = await get_itinerary_graph(db_session, itinerary.id)
        placed = next(n for n in view.nodes if n.id == node.id)
        # Same instant, re-emitted in the caller's offset (not UTC), with the
        # duration recovered from the range width.
        assert placed.starts_at == "2026-07-29T21:40:00-07:00"
        assert placed.duration_minutes == 740
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_add_node_rejects_malformed_schedule(
    db_session: AsyncSession,
) -> None:
    """A non-note node with an unparseable starts_at is a validation error,
    not a silent drop."""
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="bad schedule")
    try:
        result = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="broken",
            starts_at="not-a-datetime",
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_update_node_captures_before_and_after(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="update test")
    try:
        node = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="orig",
        )
        assert isinstance(node, Node)
        updated = await update_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            node_id=node.id,
            title="new title",
        )
        assert isinstance(updated, Node)
        assert updated.title == "new title"
        rows = (
            (
                await db_session.execute(
                    select(NodeHistory)
                    .where(NodeHistory.node_id == node.id)
                    .order_by(NodeHistory.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.op for r in rows] == ["insert", "update"]
        assert rows[1].before["title"] == "orig"
        assert rows[1].after["title"] == "new title"
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_node_writes_before_snapshot(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="delete test")
    try:
        node = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="doomed",
        )
        assert isinstance(node, Node)
        node_id = node.id
        err = await delete_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            node_id=node_id,
        )
        assert err is None
        rows = (
            (
                await db_session.execute(
                    select(NodeHistory)
                    .where(NodeHistory.node_id == node_id)
                    .order_by(NodeHistory.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.op for r in rows] == ["insert", "delete"]
        assert rows[1].before is not None
        assert rows[1].before["title"] == "doomed"
        assert rows[1].after is None
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_add_edge_writes_history(db_session: AsyncSession) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="edge test")
    try:
        a = await add_node(db_session, actor, itinerary_id=itinerary.id, type=NodeType.experience)
        b = await add_node(db_session, actor, itinerary_id=itinerary.id, type=NodeType.experience)
        assert isinstance(a, Node) and isinstance(b, Node)
        edge = await add_edge(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            from_node_id=a.id,
            to_node_id=b.id,
            type=EdgeType.follows,
        )
        assert isinstance(edge, Edge)
        rows = (
            (await db_session.execute(select(EdgeHistory).where(EdgeHistory.edge_id == edge.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].op == "insert"
        assert rows[0].after["from_node_id"] == str(a.id)
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_delete_edge_writes_before_snapshot(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="edge del")
    try:
        a = await add_node(db_session, actor, itinerary_id=itinerary.id, type=NodeType.experience)
        b = await add_node(db_session, actor, itinerary_id=itinerary.id, type=NodeType.experience)
        assert isinstance(a, Node) and isinstance(b, Node)
        edge = await add_edge(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            from_node_id=a.id,
            to_node_id=b.id,
            type=EdgeType.follows,
        )
        assert isinstance(edge, Edge)
        edge_id = edge.id
        err = await delete_edge(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            edge_id=edge_id,
        )
        assert err is None
        rows = (
            (
                await db_session.execute(
                    select(EdgeHistory)
                    .where(EdgeHistory.edge_id == edge_id)
                    .order_by(EdgeHistory.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.op for r in rows] == ["insert", "delete"]
        assert rows[1].after is None
        assert rows[1].before is not None
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_provenance_asymmetry_rejected_by_service(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="prov")
    itinerary_id = itinerary.id
    try:
        err = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary_id,
            type=NodeType.experience,
            source="ov",
            source_id=None,
        )
        assert isinstance(err, ItineraryError)
        assert err.outcome is ItineraryOutcome.INVALID_PROVENANCE
    finally:
        await _cleanup(db_session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_self_loop_edge_maps_to_validation_error(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="self loop")
    # Stash the id before the integrity-error rollback expires attribute state.
    itinerary_id = itinerary.id
    try:
        node = await add_node(
            db_session, actor, itinerary_id=itinerary_id, type=NodeType.experience
        )
        assert isinstance(node, Node)
        result = await add_edge(
            db_session,
            actor,
            itinerary_id=itinerary_id,
            from_node_id=node.id,
            to_node_id=node.id,
            type=EdgeType.follows,
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.VALIDATION_ERROR
        assert result.detail == "edges_no_self_loop"
    finally:
        await _cleanup(db_session, itinerary_id)


@integration
@pytest.mark.asyncio
async def test_cross_itinerary_parent_rejected(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itin_a = await create_itinerary(db_session, actor, title="A")
    itin_b = await create_itinerary(db_session, actor, title="B")
    try:
        parent_in_b = await add_node(
            db_session, actor, itinerary_id=itin_b.id, type=NodeType.experience
        )
        assert isinstance(parent_in_b, Node)
        result = await add_node(
            db_session,
            actor,
            itinerary_id=itin_a.id,
            type=NodeType.meal,
            parent_subgraph_id=parent_in_b.id,
        )
        assert isinstance(result, ItineraryError)
        assert result.outcome is ItineraryOutcome.INVALID_PARENT
    finally:
        await _cleanup(db_session, itin_a.id)
        await _cleanup(db_session, itin_b.id)


@integration
@pytest.mark.asyncio
async def test_unknown_itinerary_not_found(
    db_session: AsyncSession,
) -> None:
    _actor()
    result = await get_itinerary_graph(db_session, uuid.uuid4())
    assert isinstance(result, ItineraryError)
    assert result.outcome is ItineraryOutcome.NOT_FOUND


@integration
@pytest.mark.asyncio
async def test_get_itinerary_graph_assembles_subgraph(
    db_session: AsyncSession,
) -> None:
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="assembly")
    try:
        root = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="Amalfi tour",
            source="ov",
            source_id="t-1",
        )
        assert isinstance(root, Node)
        child = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            parent_subgraph_id=root.id,
            type=NodeType.meal,
            title="Lunch",
        )
        assert isinstance(child, Node)
        grandchild = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            parent_subgraph_id=child.id,
            type=NodeType.experience,
            title="Note",
        )
        assert isinstance(grandchild, Node)
        edge = await add_edge(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            from_node_id=root.id,
            to_node_id=child.id,
            type=EdgeType.follows,
        )
        assert isinstance(edge, Edge)

        # Stamp a JST tstzrange on the root so we can assert the CTE
        # serializes starts_at + duration_minutes. add_node doesn't take a
        # range, so set it directly. The child is left without a schedule.
        # Also stamp tz_offset_minutes=540 (JST) in metadata so the CTE
        # re-emits the local wall-clock offset instead of UTC.
        jst = timezone(timedelta(hours=9))
        lower = datetime(2024, 6, 20, 16, 10, tzinfo=jst)
        upper = datetime(2024, 6, 20, 16, 40, tzinfo=jst)
        await db_session.execute(
            text(
                "update public.nodes set starts_at = "
                "tstzrange(:lo, :hi, '[)'), "
                "metadata = jsonb_set("
                "  coalesce(metadata, '{}'::jsonb), "
                "  '{tz_offset_minutes}', '540'"
                ") where id = :id"
            ),
            {"lo": lower, "hi": upper, "id": root.id},
        )
        await db_session.commit()

        graph = await get_itinerary_graph(db_session, itinerary.id)
        assert not isinstance(graph, ItineraryError)
        assert graph.itinerary.id == itinerary.id
        by_id = {n.id: n for n in graph.nodes}
        assert by_id[root.id].depth == 0
        assert by_id[child.id].depth == 1
        assert by_id[grandchild.id].depth == 2
        assert len(graph.edges) == 1
        assert graph.edges[0].from_node_id == root.id
        # starts_at flows through the recursive CTE as an ISO string + an
        # integer minute span; unscheduled nodes stay (None, None).
        root_out = by_id[root.id]
        assert isinstance(root_out.starts_at, str)
        # tstzrange stores instants in UTC, but the node's metadata carries
        # tz_offset_minutes=540, so the serialized lower bound is re-emitted in
        # the JST wall-clock offset — same instant, "+09:00" tail preserved.
        assert root_out.starts_at.endswith("+09:00")
        assert datetime.fromisoformat(root_out.starts_at) == lower
        assert root_out.duration_minutes == 30
        assert by_id[child.id].starts_at is None
        assert by_id[child.id].duration_minutes is None
    finally:
        await _cleanup(db_session, itinerary.id)


@integration
@pytest.mark.asyncio
async def test_concurrent_updates_each_land_history_rows(
    db_session: AsyncSession,
) -> None:
    """Last-writer-wins is fine for M001; the invariant we guard is that
    BOTH writes produce a history row (audit cannot be lost).
    """
    actor = _actor()
    itinerary = await create_itinerary(db_session, actor, title="concurrent")
    try:
        node = await add_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            type=NodeType.experience,
            title="v0",
        )
        assert isinstance(node, Node)
        await update_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            node_id=node.id,
            title="v1",
        )
        await update_node(
            db_session,
            actor,
            itinerary_id=itinerary.id,
            node_id=node.id,
            title="v2",
        )
        rows = (
            (
                await db_session.execute(
                    select(NodeHistory)
                    .where(NodeHistory.node_id == node.id)
                    .order_by(NodeHistory.occurred_at)
                )
            )
            .scalars()
            .all()
        )
        assert [r.op for r in rows] == ["insert", "update", "update"]
        assert rows[-1].after["title"] == "v2"
    finally:
        await _cleanup(db_session, itinerary.id)
