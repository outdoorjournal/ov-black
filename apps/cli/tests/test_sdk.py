"""SDK operations over a mocked httpx transport (respx)."""

import httpx
import pytest
import respx

from ovb.errors import ApiError
from ovb.sdk import Ovb
from ovb.transport import Transport

BASE = "http://api.test"
ITIN = "11111111-1111-1111-1111-111111111111"


def _client() -> Ovb:
    return Ovb(Transport(BASE, token="jwt-abc"))


@respx.mock
async def test_create_itinerary_parses_and_sends_bearer() -> None:
    route = respx.post(f"{BASE}/itinerary").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": ITIN,
                "title": "Japan",
                "client_id": None,
                "created_by": None,
                "status": "draft",
                "approved_by": None,
                "approved_at": None,
            },
        )
    )
    async with _client() as ovb:
        res = await ovb.create_itinerary(title="Japan")
    assert str(res.id) == ITIN and res.title == "Japan"
    assert route.calls.last.request.headers["authorization"] == "Bearer jwt-abc"


@respx.mock
async def test_get_graph_parses_nodes() -> None:
    respx.get(f"{BASE}/itinerary/{ITIN}").mock(
        return_value=httpx.Response(
            200,
            json={
                "itinerary": {
                    "id": ITIN,
                    "title": "T",
                    "client_id": None,
                    "created_by": None,
                    "status": "draft",
                    "approved_by": None,
                    "approved_at": None,
                },
                "nodes": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "itinerary_id": ITIN,
                        "parent_subgraph_id": None,
                        "type": "hotel",
                        "status": "proposed",
                        "title": "Aman",
                        "source": None,
                        "source_id": None,
                        "metadata": {},
                        "cost_amount": None,
                        "cost_currency": None,
                        "cost_kind": None,
                        "starts_at": None,
                        "duration_minutes": None,
                        "depth": 0,
                    }
                ],
                "edges": [],
            },
        )
    )
    async with _client() as ovb:
        graph = await ovb.get_graph(ITIN)
    assert len(graph.nodes) == 1 and graph.nodes[0].title == "Aman"


@respx.mock
async def test_error_response_raises_apierror_with_detail() -> None:
    respx.post(f"{BASE}/sessions").mock(
        return_value=httpx.Response(404, json={"detail": "client_not_found"})
    )
    async with _client() as ovb:
        with pytest.raises(ApiError) as exc:
            await ovb.open_session(client_id=ITIN)
    assert exc.value.status == 404
    assert exc.value.detail == "client_not_found"


@respx.mock
async def test_list_clients_parses_array() -> None:
    respx.get(f"{BASE}/clients").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "99999999-9999-9999-9999-999999999999",
                    "full_name": "Jane",
                    "email": "jane@x.com",
                    "has_dossier": True,
                    "invite_status": "consumed",
                    "created_at": "2026-06-21T00:00:00Z",
                }
            ],
        )
    )
    async with _client() as ovb:
        clients = await ovb.list_clients()
    assert len(clients) == 1 and clients[0].full_name == "Jane"


@respx.mock
async def test_search_inventory_forwards_query_params() -> None:
    route = respx.get(f"{BASE}/search-inventory").mock(
        return_value=httpx.Response(200, json={"items": [], "count": 0})
    )
    async with _client() as ovb:
        await ovb.search_inventory(params={"kinds": ["flight"], "origin": "LAX"})
    sent = route.calls.last.request.url
    assert "kinds=flight" in str(sent) and "origin=LAX" in str(sent)


@respx.mock
async def test_public_route_sends_no_authorization() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    async with Ovb(Transport(BASE, token=None)) as ovb:
        res = await ovb.health()
    assert res == {"status": "ok"}
    assert "authorization" not in route.calls.last.request.headers
