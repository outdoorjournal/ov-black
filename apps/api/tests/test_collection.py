"""Router coverage for the Collection surface:

- ``POST /itinerary/{id}/nodes/from-link`` — save a pasted web link as an
  unscheduled OpenGraph card (source="web").
- ``GET  /itinerary/{id}/collection`` — the wish list: unscheduled,
  non-discarded nodes only.

Both are exercised DB-less (stub the router-bound ``add_node`` /
``get_itinerary_graph`` + the read/write gates), mirroring
``test_nodes_from_inventory``. ``fetch_link_preview`` is monkeypatched so no
network is touched.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from app.models import NodeStatus, NodeType
from app.services.link_preview import LinkPreview

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi.testclient import TestClient

_IID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


# ── POST /nodes/from-link ────────────────────────────────────────────────────


@pytest.fixture()
def captured_from_link(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Stub the router's add_node + gates + get_session so no DB is touched."""
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
            cost_amount=None,
            cost_currency=None,
            cost_kind=None,
            starts_at=None,
        )

    async def _load(_session: Any, itinerary_id: uuid.UUID) -> Any:
        return object()

    async def _writable(_session: Any, _user: Any, _itinerary: Any) -> None:
        return None

    async def _preview(url: str, **_: Any) -> LinkPreview:
        return LinkPreview(
            url=url,
            title="Kikunoi Kyoto",
            image="https://cdn.example.com/k.jpg",
            description="Kaiseki.",
        )

    from app.db import get_session
    from app.main import app as fastapi_app
    from app.routers import itineraries as routers_itineraries

    monkeypatch.setattr(routers_itineraries, "add_node", _add_node)
    monkeypatch.setattr(routers_itineraries, "_load_itinerary", _load)
    monkeypatch.setattr(routers_itineraries, "assert_itinerary_writable", _writable)
    monkeypatch.setattr(routers_itineraries, "fetch_link_preview", _preview)

    async def _session_dep() -> Any:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _session_dep
    try:
        yield captured
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


def test_from_link_requires_jwt(client: TestClient) -> None:
    resp = client.post(f"/itinerary/{_IID}/nodes/from-link", json={"url": "https://kikunoi.jp/"})
    assert resp.status_code == 401


def test_from_link_creates_unscheduled_web_note(
    client: TestClient,
    captured_from_link: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-link",
        json={"url": "https://kikunoi.jp/"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # Default kind is an unfiled note; provenance marks it a pasted link.
    assert captured_from_link["type"] is NodeType.note
    assert captured_from_link["status"] is NodeStatus.pending
    assert captured_from_link["source"] == "web"
    assert captured_from_link["source_id"] == "https://kikunoi.jp/"
    assert captured_from_link["title"] == "Kikunoi Kyoto"
    # The preview lands in metadata.snapshot with card-friendly keys; no schedule.
    snap = captured_from_link["metadata"]["snapshot"]
    assert snap["title"] == "Kikunoi Kyoto"
    assert snap["cover_image"] == "https://cdn.example.com/k.jpg"
    body = resp.json()
    assert body["source"] == "web"
    assert body["starts_at"] is None


def test_from_link_honors_kind_and_note(
    client: TestClient,
    captured_from_link: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    resp = client.post(
        f"/itinerary/{_IID}/nodes/from-link",
        json={"url": "https://kikunoi.jp/", "kind": "meal", "note": "for the anniversary dinner"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert captured_from_link["type"] is NodeType.meal
    assert captured_from_link["metadata"]["note"] == "for the anniversary dinner"


# ── GET /collection ──────────────────────────────────────────────────────────


def _out(**over: Any) -> SimpleNamespace:
    """A NodeOut-shaped stub for ``_node_response_from_out``."""
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "itinerary_id": uuid.UUID(_IID),
        "parent_subgraph_id": None,
        "type": NodeType.experience,
        "status": NodeStatus.pending,
        "title": "thing",
        "source": None,
        "source_id": None,
        "metadata": {},
        "cost_amount": None,
        "cost_currency": None,
        "cost_kind": None,
        "starts_at": None,
        "duration_minutes": None,
        "depth": 0,
        "lock_reason": None,
        "forked_from_node_id": None,
        "attached_to_node_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture()
def stub_graph(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[SimpleNamespace]]:
    """Feed a fixed node set through get_itinerary_graph; skip the read gate."""
    nodes = [
        _out(title="wishlist-experience"),  # unscheduled → in
        _out(title="wishlist-note", type=NodeType.note),  # unscheduled → in
        _out(title="scheduled", starts_at="2025-07-02T13:30:00+09:00"),  # scheduled → out
        _out(title="discarded", status=NodeStatus.discarded),  # discarded → out
    ]

    async def _graph(_session: Any, _iid: uuid.UUID) -> Any:
        return SimpleNamespace(itinerary=object(), nodes=nodes, edges=[])

    async def _readable(_session: Any, _user: Any, _itinerary: Any) -> None:
        return None

    from app.routers import itineraries as routers_itineraries

    monkeypatch.setattr(routers_itineraries, "get_itinerary_graph", _graph)
    monkeypatch.setattr(routers_itineraries, "assert_itinerary_readable", _readable)
    yield nodes


def test_collection_requires_jwt(client: TestClient) -> None:
    assert client.get(f"/itinerary/{_IID}/collection").status_code == 401


def test_collection_returns_only_unscheduled_non_discarded(
    client: TestClient,
    stub_graph: list[SimpleNamespace],
    auth_headers: dict[str, str],
) -> None:
    resp = client.get(f"/itinerary/{_IID}/collection", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["itinerary_id"] == _IID
    titles = {n["title"] for n in body["items"]}
    assert titles == {"wishlist-experience", "wishlist-note"}
    assert all(n["starts_at"] is None for n in body["items"])
