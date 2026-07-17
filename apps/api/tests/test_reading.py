"""Reading catalog routes, exercised DB-less (stub the service layer).

- ``GET /agent/reading/search`` — behind the agent token; ``search_reading_catalog``
  is stubbed so no DB is touched, proving the route validates the token and
  shapes the ranked hits.
- ``POST /me/reading-list`` — the traveler's "Add to reading list" write;
  ``resolve_client_for_auth_user`` + ``add_article_to_reading_list`` are stubbed,
  proving the metadata passes through verbatim (no OG re-fetch) and the missing-
  client case 404s.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from app.config import Settings
from app.main import app as fastapi_app
from app.models import NodeType
from app.routers import agent_internal as agent_internal_module
from app.routers import me as me_module
from app.services import agent_token as agent_token_module
from app.services.agent_token import mint_agent_token
from app.services.reading import ReadingHit
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, integration

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_SECRET = "test-agent-token-signing-secret-please-rotate"


def _settings() -> Settings:
    return Settings(agent_token_signing_secret=_SECRET)


@pytest.fixture()
def http_client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


# ── GET /agent/reading/search ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patched_agent_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_token_module, "get_settings", lambda: _settings())


def _agent_headers() -> dict[str, str]:
    token = mint_agent_token(
        session_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        agentcore_session_id="ac",
        settings=_settings(),
    )
    return {"Authorization": f"Bearer {token}"}


_HITS = [
    ReadingHit(
        id="art-1",
        title="The Granite Spires of Patagonia",
        url="https://www.climbing.com/places/patagonia/",
        source_property="Climbing",
        og_image="https://images.unsplash.com/photo-1496340077100-9573d8b77463?w=1200",
        excerpt="Fitz Roy and Cerro Torre.",
        reading_time_minutes=11,
    )
]


def test_reading_search_requires_agent_token(http_client: TestClient) -> None:
    resp = http_client.get("/agent/reading/search", params={"q": "patagonia"})
    assert resp.status_code == 401


def test_reading_search_returns_ranked_hits(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _search(_session: Any, *, query: str, limit: int = 3) -> list[ReadingHit]:
        captured["query"] = query
        captured["limit"] = limit
        return _HITS

    async def _session_dep() -> Any:
        yield object()

    monkeypatch.setattr(agent_internal_module, "search_reading_catalog", _search)
    from app.db import get_session

    fastapi_app.dependency_overrides[get_session] = _session_dep
    try:
        resp = http_client.get(
            "/agent/reading/search",
            params={"q": "patagonia", "limit": 3},
            headers=_agent_headers(),
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 200, resp.text
    assert captured == {"query": "patagonia", "limit": 3}
    body = resp.json()
    assert body["results"][0]["source_property"] == "Climbing"
    assert body["results"][0]["reading_time_minutes"] == 11


# ── POST /me/reading-list ────────────────────────────────────────────────────


@pytest.fixture()
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}


@pytest.fixture()
def stub_reading_list(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Stub me.py's client resolution + reading-list write; no DB touched."""
    captured: dict[str, Any] = {}
    itinerary_id = uuid.uuid4()
    node_id = uuid.uuid4()

    async def _resolve(_session: Any, *, user_id: uuid.UUID, email: str | None) -> Any:
        return SimpleNamespace(id=uuid.uuid4())

    async def _add(_session: Any, _actor: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(id=node_id, itinerary_id=itinerary_id)

    monkeypatch.setattr(me_module, "resolve_client_for_auth_user", _resolve)
    monkeypatch.setattr(me_module, "add_article_to_reading_list", _add)

    async def _session_dep() -> Any:
        yield object()

    from app.db import get_session

    fastapi_app.dependency_overrides[get_session] = _session_dep
    captured["_node_id"] = node_id
    captured["_itinerary_id"] = itinerary_id
    try:
        yield captured
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)


def test_reading_list_add_requires_jwt(http_client: TestClient) -> None:
    resp = http_client.post("/me/reading-list", json={"title": "t", "url": "https://x.test/a"})
    assert resp.status_code == 401


def test_reading_list_add_passes_metadata_through(
    http_client: TestClient, stub_reading_list: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    resp = http_client.post(
        "/me/reading-list",
        json={
            "title": "The Granite Spires of Patagonia",
            "url": "https://www.climbing.com/places/patagonia/",
            "publication": "Climbing",
            "og_image": "https://images.unsplash.com/photo-1496340077100-9573d8b77463?w=1200",
            "excerpt": "Fitz Roy and Cerro Torre.",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # Metadata forwarded verbatim to the service — no re-fetch of the source.
    assert stub_reading_list["title"] == "The Granite Spires of Patagonia"
    assert stub_reading_list["url"] == "https://www.climbing.com/places/patagonia/"
    assert stub_reading_list["publication"] == "Climbing"
    assert stub_reading_list["excerpt"] == "Fitz Roy and Cerro Torre."
    body = resp.json()
    assert body["node_id"] == str(stub_reading_list["_node_id"])
    assert body["itinerary_id"] == str(stub_reading_list["_itinerary_id"])


def test_reading_list_add_404_without_client(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    async def _resolve(_session: Any, *, user_id: uuid.UUID, email: str | None) -> Any:
        return None

    async def _session_dep() -> Any:
        yield object()

    monkeypatch.setattr(me_module, "resolve_client_for_auth_user", _resolve)
    from app.db import get_session

    fastapi_app.dependency_overrides[get_session] = _session_dep
    try:
        resp = http_client.post(
            "/me/reading-list",
            json={"title": "t", "url": "https://x.test/a"},
            headers=auth_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "client_not_found"


# ── Integration: the reconciled save lands an article on the client's trunk ───


@integration
async def test_add_article_to_reading_list_lands_on_client_trunk() -> None:
    """End-to-end: with no trip yet, the save spins up the client's own trunk
    and writes an unscheduled ``article`` node there — the shape + location the
    Reading destination (``isReadingArticle`` over ``listMyItineraries``) reads.
    Proves the reconciliation: reading is an article node on a trunk, not a
    separate store."""
    from app.models import Itinerary, Node
    from app.services.itineraries import ActorContext, ActorKind
    from app.services.reading import add_article_to_reading_list

    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    owner = uuid.uuid4()
    client_id = uuid.uuid4()
    itinerary_id: uuid.UUID | None = None
    try:
        async with maker() as s:
            await s.execute(
                text(
                    "insert into auth.users (id, email, is_sso_user, is_anonymous) "
                    "values (:id, :email, false, false)"
                ),
                {"id": owner, "email": f"reading-{owner}@test.local"},
            )
            await s.execute(
                text(
                    "insert into public.clients (id, owner_id, auth_user_id, full_name, email) "
                    "values (:id, :o, :a, 'Reader', :e)"
                ),
                {"id": client_id, "o": owner, "a": owner, "e": f"reading-{client_id}@x.com"},
            )
            await s.commit()

            actor = ActorContext(user_id=owner, kind=ActorKind.USER, actor_id=str(owner))
            node = await add_article_to_reading_list(
                s,
                actor,
                client_id=client_id,
                title="The Granite Spires of Patagonia",
                url="https://www.climbing.com/places/patagonia/",
                publication="Climbing",
                og_image="https://images.unsplash.com/photo-1496340077100-9573d8b77463?w=1200",
                excerpt="Fitz Roy and Cerro Torre.",
            )
            assert isinstance(node, Node), node
            itinerary_id = node.itinerary_id

            assert node.type is NodeType.article
            assert node.starts_at is None  # non-schedulable
            assert node.source == "reading_catalog"
            # Metadata shape the web toReadingItem() reads.
            assert node.metadata_["publication"] == "Climbing"
            assert node.metadata_["snapshot"]["cover_image"].startswith("https://images.unsplash")

            # Landed on a client-owned trunk (forked_from_id IS NULL) — where the
            # cross-trip Reading rack looks.
            itin = (
                await s.execute(select(Itinerary).where(Itinerary.id == itinerary_id))
            ).scalar_one()
            assert itin.client_id == client_id
            assert itin.forked_from_id is None
    finally:
        eng = create_async_engine(LOCAL_DB_URL, pool_pre_ping=False, future=True)
        try:
            async with eng.begin() as conn:
                if itinerary_id is not None:
                    await conn.execute(
                        text("delete from public.node_history where itinerary_id = :i"),
                        {"i": itinerary_id},
                    )
                    await conn.execute(
                        text("delete from public.itineraries where id = :i"), {"i": itinerary_id}
                    )
                await conn.execute(
                    text("delete from public.clients where id = :i"), {"i": client_id}
                )
                await conn.execute(text("delete from auth.users where id = :i"), {"i": owner})
        finally:
            await eng.dispose()
        await engine.dispose()
