"""Write-gate for node/edge mutations (owner / creator / advisor only).

``_has_write_relationship`` is the shared predicate (also backs the fork gate);
``assert_itinerary_writable`` raises 403 when it fails. These stub the two DB
helpers it calls (``_resolve_client_auth_user_id`` / ``_is_requester_advisor``)
so the logic — including the agent-on-a-clientless-draft creator branch — is
exercised without a database. A final route test proves the endpoint wiring.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.db import get_session
from app.main import app as fastapi_app
from app.routers import itineraries as ritin
from fastapi import HTTPException


def _user(sub: str) -> Any:
    return SimpleNamespace(sub=sub)


def _itin(*, client_id: uuid.UUID | None = None, created_by: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), client_id=client_id, created_by=created_by, status=None)


def _stub_helpers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_auth_id: uuid.UUID | None,
    is_advisor: bool,
) -> None:
    async def _resolve(_s: Any, _cid: uuid.UUID) -> uuid.UUID | None:
        return owner_auth_id

    async def _adv(_s: Any, _uid: uuid.UUID | None) -> bool:
        return is_advisor

    monkeypatch.setattr(ritin, "_resolve_client_auth_user_id", _resolve)
    monkeypatch.setattr(ritin, "_is_requester_advisor", _adv)


async def test_admits_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    caller = uuid.uuid4()
    _stub_helpers(monkeypatch, owner_auth_id=caller, is_advisor=False)
    ok = await ritin._has_write_relationship(
        object(), _user(str(caller)), _itin(client_id=uuid.uuid4())
    )
    assert ok is True


async def test_admits_creator_on_clientless_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    # The agent's concierge-created draft has client_id=None; created_by (the
    # client JWT that made it) is what readmits the agent.
    caller = uuid.uuid4()
    _stub_helpers(monkeypatch, owner_auth_id=None, is_advisor=False)
    ok = await ritin._has_write_relationship(
        object(), _user(str(caller)), _itin(client_id=None, created_by=caller)
    )
    assert ok is True


async def test_admits_advisor(monkeypatch: pytest.MonkeyPatch) -> None:
    caller = uuid.uuid4()
    _stub_helpers(monkeypatch, owner_auth_id=uuid.uuid4(), is_advisor=True)
    ok = await ritin._has_write_relationship(
        object(), _user(str(caller)), _itin(client_id=uuid.uuid4(), created_by=uuid.uuid4())
    )
    assert ok is True


async def test_rejects_stranger(monkeypatch: pytest.MonkeyPatch) -> None:
    caller = uuid.uuid4()
    _stub_helpers(monkeypatch, owner_auth_id=uuid.uuid4(), is_advisor=False)
    itinerary = _itin(client_id=uuid.uuid4(), created_by=uuid.uuid4())
    assert await ritin._has_write_relationship(object(), _user(str(caller)), itinerary) is False
    with pytest.raises(HTTPException) as exc:
        await ritin.assert_itinerary_writable(object(), _user(str(caller)), itinerary)
    assert exc.value.status_code == 403
    assert exc.value.detail == "forbidden"


def test_post_node_as_stranger_returns_403(
    client: Any,
    make_token: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint loads + gates before touching the service: a stranger 403s."""
    iid = uuid.uuid4()

    async def _load(_s: Any, _id: uuid.UUID) -> Any:
        return _itin(client_id=uuid.uuid4(), created_by=uuid.uuid4())

    _stub_helpers(monkeypatch, owner_auth_id=uuid.uuid4(), is_advisor=False)
    monkeypatch.setattr(ritin, "_load_itinerary", _load)

    async def _dep() -> Any:
        yield object()

    fastapi_app.dependency_overrides[get_session] = _dep
    try:
        headers = {"Authorization": f"Bearer {make_token(sub=str(uuid.uuid4()))}"}
        resp = client.post(
            f"/itinerary/{iid}/nodes",
            json={"type": "note", "title": "x", "starts_at": "2025-07-02T19:30:00+09:00"},
            headers=headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "forbidden"
    finally:
        fastapi_app.dependency_overrides.pop(get_session, None)
