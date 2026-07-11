"""Router coverage for POST /itinerary/{id}/nodes/from-inventory (M002/B2).

The endpoint fetches a live inventory item through the registry, derives the
typed card metadata, and creates a node via the normal ``add_node`` path. We
stub ``add_node`` (router-module bound name) + ``get_session`` so no DB is
needed, and inject a fake registry whose ``duffel`` provider returns a real
:class:`FlightItem` parsed from the committed fixture — proving a Duffel offer
becomes a ``flight`` node carrying FlightCardAttrs (cabin / times / route).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from app.inventory.providers.duffel import normalize_duffel_offer
from app.inventory.registry import (
    InventoryCtx,
    InventoryProvider,
    InventoryProviderRegistry,
)
from app.inventory.schemas import FlightItem, InventoryItem
from app.main import app as fastapi_app
from app.models import NodeType
from app.routers.inventory import get_inventory_registry
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "duffel_offers.json"


def _flight_item() -> FlightItem:
    offer = json.loads(FIXTURE_PATH.read_text())["data"][0]
    item = normalize_duffel_offer(offer)
    assert isinstance(item, FlightItem)
    return item


class FakeDuffelProvider(InventoryProvider):
    source = "duffel"

    def __init__(self, item: InventoryItem | None) -> None:
        self._item = item
        self.detail_calls: list[str] = []

    async def search(self, **_: Any) -> list[InventoryItem]:  # pragma: no cover
        return []

    async def get_detail(self, *, source_id: str, ctx: InventoryCtx) -> InventoryItem | None:
        self.detail_calls.append(source_id)
        return self._item


@pytest.fixture()
def captured_add_node(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the router's add_node + get_session so no DB is touched."""
    captured: dict[str, Any] = {}

    async def _add_node(session: Any, actor: Any, **kwargs: Any) -> Any:
        captured["actor"] = actor
        captured.update(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            itinerary_id=kwargs["itinerary_id"],
            parent_subgraph_id=kwargs.get("parent_subgraph_id"),
            type=kwargs["type"],
            status=kwargs["status"],
            title=kwargs["title"],
            source=kwargs["source"],
            source_id=kwargs["source_id"],
            metadata_=kwargs["metadata"],
            cost_amount=kwargs.get("cost_amount"),
            cost_currency=kwargs.get("cost_currency"),
            cost_kind=kwargs.get("cost_kind"),
            starts_at=None,
        )

    from app.routers import itineraries as routers_itineraries

    monkeypatch.setattr(routers_itineraries, "add_node", _add_node)

    # The endpoint pre-loads the itinerary and gates it with
    # ``assert_itinerary_writable``; this DB-less unit stubs both (non-None load
    # to skip the 404 branch, no-op writable = authorized).
    async def _load(_session: Any, itinerary_id: uuid.UUID) -> Any:
        return object()

    async def _writable(_session: Any, _user: Any, _itinerary: Any) -> None:
        return None

    monkeypatch.setattr(routers_itineraries, "_load_itinerary", _load)
    monkeypatch.setattr(routers_itineraries, "assert_itinerary_writable", _writable)

    async def _session_dep() -> Any:
        yield object()

    from app.db import get_session

    fastapi_app.dependency_overrides[get_session] = _session_dep
    try:
        yield captured
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def override_registry():
    provider = FakeDuffelProvider(_flight_item())
    registry = InventoryProviderRegistry()
    registry.register(provider)
    fastapi_app.dependency_overrides[get_inventory_registry] = lambda: registry
    try:
        yield provider
    finally:
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


_IID = "11111111-1111-1111-1111-111111111111"


def test_requires_jwt(client: TestClient, override_registry: Any) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "duffel", "source_id": "off_0000ANA105"},
    )
    assert resp.status_code == 401


def test_creates_flight_node_with_card_attrs(
    client: TestClient,
    captured_add_node: dict[str, Any],
    override_registry: FakeDuffelProvider,
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "duffel", "source_id": "off_0000ANA105"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # The provider was asked to (re-)fetch the offer.
    assert override_registry.detail_calls == ["off_0000ANA105"]
    # add_node received a flight node with typed FlightCardAttrs metadata.
    assert captured_add_node["type"] is NodeType.flight
    assert captured_add_node["source"] == "duffel"
    assert captured_add_node["source_id"] == "off_0000ANA105"
    assert captured_add_node["status"].value == "pending"
    meta = captured_add_node["metadata"]
    assert meta["kind"] == "flight"
    assert meta["iata_from"] == "LAX"
    assert meta["iata_to"] == "HND"
    assert meta["cabin"] == "business"
    assert meta["depart_at"].startswith("2026-07-10T11:05:00")
    # Timed inventory schedules itself: the flight lands ON the timeline at its
    # depart_at (with the leg duration) instead of unscheduled in the Collection,
    # so it's immediately visible in the journal rather than a silent wish-list add.
    assert captured_add_node["starts_at"] == meta["depart_at"]
    assert captured_add_node["duration_minutes"] == 755
    # B4: the Duffel offer's total_amount is promoted to first-class cost
    # columns (a flight is a whole-booking total, D-COST cost_kind=total).
    from decimal import Decimal

    from app.models import CostKind

    assert captured_add_node["cost_amount"] == Decimal("6420.50")
    assert captured_add_node["cost_currency"] == "USD"
    assert captured_add_node["cost_kind"] is CostKind.total
    # Response echoes the persisted node.
    body = resp.json()
    assert body["type"] == "flight"
    assert body["metadata"]["cabin"] == "business"
    assert body["cost_amount"] == "6420.50"
    assert body["cost_currency"] == "USD"
    assert body["cost_kind"] == "total"


def test_unknown_item_returns_404(
    client: TestClient,
    captured_add_node: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    provider = FakeDuffelProvider(None)  # get_detail → None
    registry = InventoryProviderRegistry()
    registry.register(provider)
    fastapi_app.dependency_overrides[get_inventory_registry] = lambda: registry
    try:
        resp = client.post(
            f"/itinerary/{_IID}/nodes/from-inventory",
            json={"source": "duffel", "source_id": "off_expired"},
            headers=auth_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "inventory_not_found"
    assert "type" not in captured_add_node  # add_node never called


def test_unknown_source_returns_400(
    client: TestClient,
    captured_add_node: dict[str, Any],
    override_registry: FakeDuffelProvider,
    auth_headers: dict[str, str],
) -> None:
    # Registry has only 'duffel'; asking for 'ratehawk' raises UnknownSourceError.
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "ratehawk", "source_id": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "unknown_source"


# ── round-trip flight → one node per leg ───────────────────────────────────


def _round_trip_flight_item() -> FlightItem:
    def _place(code: str, tz: str) -> dict[str, Any]:
        return {"iata_code": code, "city_name": code, "time_zone": tz}

    dtw, nrt = _place("DTW", "America/Detroit"), _place("NRT", "Asia/Tokyo")
    item = normalize_duffel_offer(
        {
            "id": "off_roundtrip",
            "total_amount": "4200.00",
            "total_currency": "USD",
            "slices": [
                {
                    "origin": dtw,
                    "destination": nrt,
                    "segments": [
                        {
                            "origin": dtw,
                            "destination": nrt,
                            "departing_at": "2026-09-01T11:00:00",
                            "arriving_at": "2026-09-02T14:30:00",
                        }
                    ],
                },
                {
                    "origin": nrt,
                    "destination": dtw,
                    "segments": [
                        {
                            "origin": nrt,
                            "destination": dtw,
                            "departing_at": "2026-09-10T17:00:00",
                            "arriving_at": "2026-09-10T15:30:00",
                        }
                    ],
                },
            ],
        }
    )
    assert isinstance(item, FlightItem)
    return item


@pytest.fixture()
def override_round_trip_registry():
    provider = FakeDuffelProvider(_round_trip_flight_item())
    registry = InventoryProviderRegistry()
    registry.register(provider)
    fastapi_app.dependency_overrides[get_inventory_registry] = lambda: registry
    try:
        yield provider
    finally:
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


def test_round_trip_flight_creates_two_nodes(
    client: TestClient,
    captured_graph_writes: dict[str, list[dict[str, Any]]],
    override_round_trip_registry: FakeDuffelProvider,
    auth_headers: dict[str, str],
) -> None:
    """A round-trip Duffel offer lands as outbound + return nodes.

    Both share the offer's source_id (booking is atomic); the whole-ticket fare
    rides only the outbound so trip totals don't double-count. The response is
    the outbound with the return under ``additional_nodes``.
    """
    from decimal import Decimal

    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "duffel", "source_id": "off_roundtrip"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    nodes = captured_graph_writes["nodes"]
    assert len(nodes) == 2
    outbound, ret = nodes
    assert outbound["metadata"]["iata_from"] == "DTW"
    assert outbound["metadata"]["iata_to"] == "NRT"
    assert ret["metadata"]["iata_from"] == "NRT"
    assert ret["metadata"]["iata_to"] == "DTW"
    # Same bookable offer.
    assert outbound["source_id"] == ret["source_id"] == "off_roundtrip"
    # Fare on the outbound only.
    assert outbound["cost_amount"] == Decimal("4200.00")
    assert ret["cost_amount"] is None
    # Each leg scheduled at its own departure.
    assert outbound["starts_at"].startswith("2026-09-01T11:00:00")
    assert ret["starts_at"].startswith("2026-09-10T17:00:00")

    body = resp.json()
    assert body["metadata"]["iata_to"] == "NRT"
    assert len(body["additional_nodes"]) == 1
    assert body["additional_nodes"][0]["metadata"]["iata_to"] == "DTW"
    # The nested leg carries no siblings of its own.
    assert body["additional_nodes"][0]["additional_nodes"] == []


# ── multi-day subgraph materialization (OV adventures) ─────────────────────

OV_TRIP_FIXTURE = Path(__file__).parent / "fixtures" / "ov_trip_simien.json"


def _simien_item() -> Any:
    from app.inventory.providers.ov import normalize_ov_entry

    entry = json.loads(OV_TRIP_FIXTURE.read_text())["data"]
    item = normalize_ov_entry(entry)
    assert len(item.itinerary_days) == 4
    return item


class FakeOVProvider(InventoryProvider):
    source = "ov"

    def __init__(self, item: InventoryItem | None) -> None:
        self._item = item

    async def search(self, **_: Any) -> list[InventoryItem]:  # pragma: no cover
        return []

    async def get_detail(self, *, source_id: str, ctx: InventoryCtx) -> InventoryItem | None:
        return self._item


@pytest.fixture()
def captured_graph_writes(
    captured_add_node: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[dict[str, Any]]]:
    """Capture every add_node/add_edge across router + subgraph service.

    ``materialize_day_subgraph`` calls the service-module bound names, so the
    router-level stub from ``captured_add_node`` doesn't see child writes —
    patch the subgraph module too, recording calls in order.
    """
    calls: dict[str, list[dict[str, Any]]] = {"nodes": [], "edges": []}

    async def _add_node(session: Any, actor: Any, **kwargs: Any) -> Any:
        calls["nodes"].append(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            itinerary_id=kwargs["itinerary_id"],
            parent_subgraph_id=kwargs.get("parent_subgraph_id"),
            type=kwargs["type"],
            status=kwargs["status"],
            title=kwargs["title"],
            source=kwargs.get("source"),
            source_id=kwargs.get("source_id"),
            metadata_=kwargs["metadata"],
            cost_amount=kwargs.get("cost_amount"),
            cost_currency=kwargs.get("cost_currency"),
            cost_kind=kwargs.get("cost_kind"),
            starts_at=None,
        )

    async def _add_edge(session: Any, actor: Any, **kwargs: Any) -> Any:
        calls["edges"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), **kwargs)

    from app.routers import itineraries as routers_itineraries
    from app.services import subgraph as subgraph_service

    monkeypatch.setattr(routers_itineraries, "add_node", _add_node)
    monkeypatch.setattr(subgraph_service, "add_node", _add_node)
    monkeypatch.setattr(subgraph_service, "add_edge", _add_edge)
    return calls


@pytest.fixture()
def override_ov_registry():
    provider = FakeOVProvider(_simien_item())
    registry = InventoryProviderRegistry()
    registry.register(provider)
    fastapi_app.dependency_overrides[get_inventory_registry] = lambda: registry
    try:
        yield provider
    finally:
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


def test_multi_day_item_materializes_day_subgraph(
    client: TestClient,
    captured_graph_writes: dict[str, list[dict[str, Any]]],
    override_ov_registry: FakeOVProvider,
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "ov", "source_id": "simien-4d"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    nodes = captured_graph_writes["nodes"]
    assert len(nodes) == 5  # parent + 4 days
    parent, children = nodes[0], nodes[1:]
    assert parent["source"] == "ov"
    assert parent["parent_subgraph_id"] is None

    # Response is the parent node, not a child.
    assert resp.json()["parent_subgraph_id"] is None
    assert resp.json()["title"] == parent["title"]

    for i, child in enumerate(children, start=1):
        assert child["parent_subgraph_id"] is not None
        assert child["title"].startswith(f"Day {i} — ")
        assert child["status"] == parent["status"]
        day_meta = child["metadata"]["subgraph_day"]
        assert day_meta["index"] == i
        assert isinstance(day_meta.get("lat"), float)
        # Derived content: no provenance of its own.
        assert child.get("source") is None
    # All children share one parent id.
    assert len({str(c["parent_subgraph_id"]) for c in children}) == 1

    # Days chained by follows edges: 1→2→3→4.
    edges = captured_graph_writes["edges"]
    assert len(edges) == 3
    assert all(e["type"].value == "follows" for e in edges)
    assert all(e["metadata"] == {"reason": "day_sequence"} for e in edges)


def test_expand_days_false_creates_only_parent(
    client: TestClient,
    captured_graph_writes: dict[str, list[dict[str, Any]]],
    override_ov_registry: FakeOVProvider,
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={"source": "ov", "source_id": "simien-4d", "expand_days": False},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert len(captured_graph_writes["nodes"]) == 1
    assert captured_graph_writes["edges"] == []


def test_nested_target_skips_materialization(
    client: TestClient,
    captured_graph_writes: dict[str, list[dict[str, Any]]],
    override_ov_registry: FakeOVProvider,
    auth_headers: dict[str, str],
) -> None:
    """Creating inside an existing subgraph never nests another one."""
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-inventory",
        json={
            "source": "ov",
            "source_id": "simien-4d",
            "parent_subgraph_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert len(captured_graph_writes["nodes"]) == 1
    assert captured_graph_writes["edges"] == []
