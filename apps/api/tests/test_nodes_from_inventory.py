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
    assert captured_add_node["status"].value == "proposed"
    meta = captured_add_node["metadata"]
    assert meta["kind"] == "flight"
    assert meta["iata_from"] == "LAX"
    assert meta["iata_to"] == "HND"
    assert meta["cabin"] == "business"
    assert meta["depart_at"].startswith("2026-07-10T11:05:00")
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
