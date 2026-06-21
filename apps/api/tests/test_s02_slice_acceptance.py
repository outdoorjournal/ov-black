"""S02 slice acceptance — one test per bullet of the slice demo.

Each test exercises the *real* HTTP surface end-to-end against a locally
running Supabase Postgres, with the OV adapter wired to an
``httpx.MockTransport`` seeded from the committed
``tests/fixtures/ov_search_como.json`` so the suite is hermetic against
the live OV API. The mock provider runs unmodified — its fixture is
already part of the repo.

Skipped automatically (not failed) on a fresh checkout where Supabase is
not running, mirroring the ``_supabase_running()`` pattern in
``tests/test_invites.py``.
"""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.config import Settings
from app.db import get_session
from app.inventory.providers.mock import MockProvider
from app.inventory.providers.ov import OVProvider
from app.inventory.registry import InventoryProviderRegistry
from app.inventory.schemas import InventoryItem
from app.main import app as fastapi_app
from app.routers.inventory import get_inventory_registry
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 54322

OV_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ov_search_como.json"

_ITEMS_ADAPTER: TypeAdapter[list[InventoryItem]] = TypeAdapter(list[InventoryItem])


def _supabase_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((LOCAL_HOST, LOCAL_PORT))
        except OSError:
            return False
        return True


pytestmark = pytest.mark.skipif(
    not _supabase_running(),
    reason="local Supabase (127.0.0.1:54322) not running — `supabase start` first",
)


# ── Inventory registry override (real MockProvider, faked OVProvider) ──────


@pytest.fixture(scope="module")
def ov_fixture() -> dict[str, Any]:
    return json.loads(OV_FIXTURE_PATH.read_text())


@pytest.fixture()
def faked_registry(ov_fixture: dict[str, Any]) -> InventoryProviderRegistry:
    """A registry with the real MockProvider + an OVProvider whose HTTP
    client is backed by ``httpx.MockTransport`` returning the fixture."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ov_fixture)

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, timeout=5.0)
    settings = Settings(
        ov_base_url="https://www.outdoorvoyage.com",
        ov_api_key="",
    )
    ov = OVProvider(client=http_client, settings=settings)
    mock = MockProvider()

    registry = InventoryProviderRegistry()
    registry.register(ov)
    registry.register(mock)
    return registry


# ── App + JWT plumbing ─────────────────────────────────────────────────────


@pytest.fixture()
def overrides(
    faked_registry: InventoryProviderRegistry,
):
    """Wire registry + session dependency overrides for one test.

    The session dep creates a per-request engine on whatever event loop
    the TestClient is running. Mixing a module-scoped engine with
    TestClient's portal-spawned loop produces cross-loop asyncpg errors,
    so we eat the small connection-setup cost per request instead.
    """

    async def _session_dep():
        eng = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        maker = async_sessionmaker(bind=eng, expire_on_commit=False, class_=AsyncSession)
        try:
            async with maker() as s:
                yield s
        finally:
            await eng.dispose()

    def _registry_dep() -> InventoryProviderRegistry:
        return faked_registry

    fastapi_app.dependency_overrides[get_session] = _session_dep
    fastapi_app.dependency_overrides[get_inventory_registry] = _registry_dep
    try:
        yield
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
        fastapi_app.dependency_overrides.pop(get_inventory_registry, None)


@pytest.fixture()
def client(overrides) -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def auth_headers(make_token) -> Iterator[dict[str, str]]:
    """Real JWT minted by the conftest factory against a seeded auth user.

    The S08 draft-read gate requires ``actor.user_id == created_by`` for
    a caller to read back their own draft. We mint a random UUID sub and
    seed the matching ``auth.users`` row so ``itineraries.created_by``'s
    FK to ``auth.users(id)`` is satisfied. The row is torn down on
    teardown.
    """
    user_id = uuid.uuid4()

    async def _seed(eng: Any) -> None:
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                    "values (:id, :email, false, false)"
                ),
                {"id": user_id, "email": f"s02-{user_id}@test.local"},
            )

    async def _drop(eng: Any) -> None:
        async with eng.begin() as conn:
            await conn.execute(text("delete from auth.users where id = :i"), {"i": user_id})

    _run_with_engine(_seed)
    try:
        yield {"Authorization": f"Bearer {make_token(sub=str(user_id))}"}
    finally:
        _run_with_engine(_drop)


# ── DB-side helpers (run via asyncio.run() so each gets a fresh loop) ──────


def _run_with_engine(coro_fn) -> Any:
    """Invoke an async fn that takes (engine,) on a fresh loop.

    Avoids cross-loop asyncpg errors: every call gets its own loop, its
    own engine, and the engine is disposed before the loop closes.
    """
    import asyncio

    async def _go() -> Any:
        eng = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            return await coro_fn(eng)
        finally:
            await eng.dispose()

    return asyncio.run(_go())


def _cleanup(itinerary_id: uuid.UUID) -> None:
    """Drop history + itinerary so each test starts clean."""

    async def _do(eng) -> None:
        async with eng.begin() as conn:
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

    _run_with_engine(_do)


def _fetch_scalar(sql: str, **params: Any) -> Any:
    """Run a single SELECT and return the scalar result on a fresh loop."""

    async def _do(eng) -> Any:
        async with eng.begin() as conn:
            return (await conn.execute(text(sql), params)).scalar_one()

    return _run_with_engine(_do)


def _fetch_scalars(sql: str, **params: Any) -> list[Any]:
    """Run a SELECT and return the scalars list on a fresh loop."""

    async def _do(eng) -> list[Any]:
        async with eng.begin() as conn:
            return list((await conn.execute(text(sql), params)).scalars().all())

    return _run_with_engine(_do)


# ── Slice acceptance tests (one per demo bullet) ───────────────────────────


def test_post_itinerary_creates_graph(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: POST /itinerary creates a graph."""
    resp = client.post(
        "/itinerary",
        json={"title": "S02 acceptance — create"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    itinerary_id = uuid.UUID(body["id"])

    try:
        # Row genuinely landed in public.itineraries — not just a 201 echo.
        title = _fetch_scalar(
            "select title from public.itineraries where id = :i",
            i=itinerary_id,
        )
        assert title == "S02 acceptance — create"
    finally:
        _cleanup(itinerary_id)


def test_search_inventory_keyword_como_returns_ov_items(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: search_inventory(keyword='como') returns OV-sourced items.

    Uses httpx.MockTransport seeded from the committed fixture.
    """
    resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) >= 1
    assert all(item["source"] == "ov" for item in items)
    # Re-parse through the discriminated union — drift here would fail
    # the slice's "same-shape" guarantee.
    _ITEMS_ADAPTER.validate_python(items)


def test_search_inventory_mock_scope_returns_same_shape(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: a mock-scoped call returns fixture items in the SAME
    InventoryItem shape as OV.

    "Same shape" means the response items validate against the same
    discriminated union AND share the structural top-level keys with OV
    items — that is the contract that lets downstream consumers (cards,
    api-client, agent tools) treat the two sources identically.
    """
    ov_resp = client.get("/search-inventory?source=ov&keyword=como", headers=auth_headers)
    mock_resp = client.get("/search-inventory?source=mock", headers=auth_headers)
    assert ov_resp.status_code == 200, ov_resp.text
    assert mock_resp.status_code == 200, mock_resp.text

    ov_items = ov_resp.json()["items"]
    mock_items = mock_resp.json()["items"]
    assert ov_items and mock_items
    assert all(i["source"] == "mock" for i in mock_items)

    # Both validate as the same union — primary "same shape" guarantee.
    _ITEMS_ADAPTER.validate_python(mock_items)
    _ITEMS_ADAPTER.validate_python(ov_items)

    # Top-level base-class keys must overlap. We compare on
    # InventoryItemBase fields rather than the per-variant additions.
    base_fields = {
        "source",
        "source_id",
        "title",
        "description",
        "photos",
        "location",
        "price",
        "editorial_links",
        "tags",
        "raw",
        "kind",
    }
    for item in ov_items:
        assert base_fields.issubset(item.keys()), (
            f"OV item missing base fields: {base_fields - item.keys()}"
        )
    for item in mock_items:
        assert base_fields.issubset(item.keys()), (
            f"Mock item missing base fields: {base_fields - item.keys()}"
        )


def test_get_itinerary_graph_returns_assembled_view(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: after building a non-trivial graph, GET /itinerary/{id}
    returns nodes (with depth) + edges in the assembled shape.
    """
    create = client.post(
        "/itinerary",
        json={"title": "S02 acceptance — graph"},
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    itinerary_id = uuid.UUID(create.json()["id"])

    try:
        # Root → child (subgraph parent) → two grandchildren + an edge to
        # a sibling alternative.
        root = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={"type": "experience", "title": "Root"},
            headers=auth_headers,
        )
        assert root.status_code == 201, root.text
        root_id = root.json()["id"]

        sub = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={
                "type": "meal",
                "title": "Sub",
                "parent_subgraph_id": root_id,
            },
            headers=auth_headers,
        )
        assert sub.status_code == 201, sub.text
        sub_id = sub.json()["id"]

        c1 = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={
                "type": "experience",
                "title": "Child 1",
                "parent_subgraph_id": sub_id,
            },
            headers=auth_headers,
        )
        assert c1.status_code == 201, c1.text
        c1_id = c1.json()["id"]

        c2 = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={
                "type": "experience",
                "title": "Child 2",
                "parent_subgraph_id": sub_id,
            },
            headers=auth_headers,
        )
        assert c2.status_code == 201, c2.text
        c2_id = c2.json()["id"]

        edge = client.post(
            f"/itinerary/{itinerary_id}/edges",
            json={
                "from_node_id": c1_id,
                "to_node_id": c2_id,
                "type": "alternative_to",
            },
            headers=auth_headers,
        )
        assert edge.status_code == 201, edge.text

        graph = client.get(f"/itinerary/{itinerary_id}", headers=auth_headers)
        assert graph.status_code == 200, graph.text
        body = graph.json()
        assert body["itinerary"]["id"] == str(itinerary_id)
        nodes_by_id = {n["id"]: n for n in body["nodes"]}
        assert len(nodes_by_id) == 4
        # Depth invariants from the recursive CTE.
        assert nodes_by_id[root_id]["depth"] == 0
        assert nodes_by_id[sub_id]["depth"] == 1
        assert nodes_by_id[c1_id]["depth"] == 2
        assert nodes_by_id[c2_id]["depth"] == 2
        assert len(body["edges"]) == 1
        assert body["edges"][0]["type"] == "alternative_to"
    finally:
        _cleanup(itinerary_id)


def test_every_mutation_produces_history_row(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: every node + edge mutation lands a row in *_history.

    Performs node insert/update/delete and edge insert/delete (5 mutations)
    then queries node_history + edge_history directly to confirm each one
    produced exactly one history row in the expected order.
    """
    create = client.post(
        "/itinerary",
        json={"title": "S02 acceptance — history"},
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    itinerary_id = uuid.UUID(create.json()["id"])

    try:
        n1 = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={"type": "experience", "title": "v0"},
            headers=auth_headers,
        )
        assert n1.status_code == 201, n1.text
        n1_id = uuid.UUID(n1.json()["id"])

        # Second node so we can insert an edge between them.
        n2 = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={"type": "experience", "title": "other"},
            headers=auth_headers,
        )
        assert n2.status_code == 201, n2.text
        n2_id = uuid.UUID(n2.json()["id"])

        upd = client.patch(
            f"/itinerary/{itinerary_id}/nodes/{n1_id}",
            json={"title": "v1"},
            headers=auth_headers,
        )
        assert upd.status_code == 200, upd.text

        edge = client.post(
            f"/itinerary/{itinerary_id}/edges",
            json={
                "from_node_id": str(n1_id),
                "to_node_id": str(n2_id),
                "type": "follows",
            },
            headers=auth_headers,
        )
        assert edge.status_code == 201, edge.text
        edge_id = uuid.UUID(edge.json()["id"])

        del_edge = client.delete(
            f"/itinerary/{itinerary_id}/edges/{edge_id}",
            headers=auth_headers,
        )
        assert del_edge.status_code == 204

        del_node = client.delete(
            f"/itinerary/{itinerary_id}/nodes/{n1_id}",
            headers=auth_headers,
        )
        assert del_node.status_code == 204

        # Read the history tables directly:
        #   node_history(n1): insert, update, delete   → 3 rows
        #   node_history(n2): insert                   → 1 row
        #   edge_history(edge): insert, delete         → 2 rows
        node_ops = _fetch_scalars(
            "select op from public.node_history where itinerary_id = :i order by occurred_at",
            i=itinerary_id,
        )
        edge_ops = _fetch_scalars(
            "select op from public.edge_history where itinerary_id = :i order by occurred_at",
            i=itinerary_id,
        )
        # 4 node mutations: insert n1, insert n2, update n1, delete n1.
        assert node_ops == ["insert", "insert", "update", "delete"]
        # 2 edge mutations: insert, delete.
        assert edge_ops == ["insert", "delete"]
    finally:
        _cleanup(itinerary_id)


def test_inventory_sourced_nodes_carry_source_and_source_id(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Demo bullet: every inventory-sourced node carries source + source_id;
    asymmetric provenance is rejected by the nodes_provenance_complete check.
    """
    # First fetch a real OV item so we use a genuine source_id (not synthetic).
    search = client.get(
        "/search-inventory?source=ov&keyword=como&limit=1",
        headers=auth_headers,
    )
    assert search.status_code == 200, search.text
    items = search.json()["items"]
    assert items, "fixture should yield at least one OV item"
    src_id = items[0]["source_id"]
    assert src_id

    create = client.post(
        "/itinerary",
        json={"title": "S02 acceptance — provenance"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    itinerary_id = uuid.UUID(create.json()["id"])

    try:
        # Happy path: source + source_id together → 201 and round-trips.
        ok = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={
                "type": "experience",
                "title": "from OV",
                "source": "ov",
                "source_id": src_id,
            },
            headers=auth_headers,
        )
        assert ok.status_code == 201, ok.text
        body = ok.json()
        assert body["source"] == "ov"
        assert body["source_id"] == src_id

        graph = client.get(f"/itinerary/{itinerary_id}", headers=auth_headers)
        assert graph.status_code == 200
        nodes = graph.json()["nodes"]
        assert any(n["source"] == "ov" and n["source_id"] == src_id for n in nodes)

        # Provenance asymmetry: source set, source_id null → 400 with the
        # constraint name surfaced in detail.
        bad = client.post(
            f"/itinerary/{itinerary_id}/nodes",
            json={
                "type": "experience",
                "title": "missing source_id",
                "source": "ov",
            },
            headers=auth_headers,
        )
        assert bad.status_code == 400, bad.text
        # The router maps INVALID_PROVENANCE outcome and the service surfaces
        # either the static message or the DB constraint name. Either should
        # mention source_id so a future agent can grep the failure.
        detail = bad.json()["detail"]
        assert "source_id" in detail or detail == "nodes_provenance_complete", detail
    finally:
        _cleanup(itinerary_id)
