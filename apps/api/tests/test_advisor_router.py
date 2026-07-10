"""Router-level coverage for the /advisor surface (Wave F).

Loaders are stubbed at the router module (the services have their own suites);
this file asserts the HTTP contract: advisor gate, cursor/kind validation,
clamping, and response envelopes. No Postgres — runs on a fresh checkout.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.main import app as fastapi_app
from app.routers import advisor as advisor_module
from app.services.activity import ActivityEvent
from app.services.advisor_overview import (
    BillingRow,
    ClientCounts,
    ItineraryCounts,
    Portfolio,
    SessionStats,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
_ADVISOR = uuid.uuid4()


@pytest.fixture()
def auth_headers(make_token: Any) -> dict[str, str]:
    """A middleware-valid Bearer token; app-level identity comes from the
    ``require_advisor`` override."""
    return {"Authorization": f"Bearer {make_token(sub=str(_ADVISOR))}"}


@pytest.fixture()
def as_advisor() -> Iterator[None]:
    async def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            sub=str(_ADVISOR),
            email="advisor@example.com",
            role="authenticated",
            claims={"sub": str(_ADVISOR)},
        )

    async def _session() -> Any:
        yield object()  # loaders are stubbed; the session is never touched

    fastapi_app.dependency_overrides[require_advisor] = _dep
    fastapi_app.dependency_overrides[get_session] = _session
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)
        fastapi_app.dependency_overrides.pop(get_session, None)


@pytest.fixture()
def as_non_advisor() -> Iterator[None]:
    async def _dep() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


def _portfolio() -> Portfolio:
    return Portfolio(
        clients=ClientCounts(total=2, uninvited=1, pending=0, active=1),
        itineraries=ItineraryCounts(
            total=3, in_studio=2, with_traveler=1, approved=0, open_forks=1, reconcile_requested=1
        ),
        billing=[
            BillingRow(
                currency="USD",
                invoiced=Decimal("100"),
                paid=Decimal("40"),
                outstanding=Decimal("60"),
            )
        ],
        sessions=SessionStats(active=1, turns_7d=5, errored_turns_7d=0, avg_latency_ms_7d=900),
        generated_at=_NOW,
    )


def _event(i: int) -> ActivityEvent:
    return ActivityEvent(
        kind="payment",
        at=_NOW,
        source_id=str(i),
        client_id=uuid.uuid4(),
        itinerary_id=None,
        itinerary_title=None,
        actor_kind=None,
        title="Deposit",
        op="succeeded",
        status_before=None,
        status_after=None,
        amount=Decimal("10"),
        currency="USD",
        ref_id=None,
    )


def test_all_advisor_routes_403_for_non_advisors(
    as_non_advisor: None, auth_headers: dict[str, str]
) -> None:
    with TestClient(fastapi_app) as client:
        for path in ("/advisor/overview", "/advisor/activity", "/advisor/money"):
            response = client.get(path, headers=auth_headers)
            assert response.status_code == 403, path
            assert response.json()["detail"] == "advisor_only"


def test_overview_envelope(
    as_advisor: None, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _load(session: Any, *, advisor_id: uuid.UUID) -> Portfolio:
        assert advisor_id == _ADVISOR
        return _portfolio()

    monkeypatch.setattr(advisor_module, "load_advisor_overview", _load)
    with TestClient(fastapi_app) as client:
        body = client.get("/advisor/overview", headers=auth_headers).json()
    assert body["clients"]["total"] == 2
    assert body["itineraries"]["reconcile_requested"] == 1
    assert body["billing"][0] == {
        "currency": "USD",
        "invoiced": "100",
        "paid": "40",
        "outstanding": "60",
    }
    assert body["sessions"]["avg_latency_ms_7d"] == 900


def test_activity_pages_and_emits_next_cursor(
    as_advisor: None, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _load(session: Any, **kwargs: Any) -> list[ActivityEvent]:
        captured.update(kwargs)
        return [_event(i) for i in range(kwargs["limit"])]

    monkeypatch.setattr(advisor_module, "load_advisor_activity", _load)
    with TestClient(fastapi_app) as client:
        body = client.get(
            "/advisor/activity?limit=2&kinds=payment,node_changed", headers=auth_headers
        ).json()
    assert captured["limit"] == 2
    assert captured["kinds"] == frozenset({"payment", "node_changed"})
    assert len(body["events"]) == 2
    assert body["next_cursor"] is not None  # full page → resumable
    assert body["events"][0]["amount"] == "10"


def test_activity_rejects_bad_cursor_and_unknown_kind(
    as_advisor: None, auth_headers: dict[str, str]
) -> None:
    with TestClient(fastapi_app) as client:
        bad_cursor = client.get("/advisor/activity?cursor=!!!garbage", headers=auth_headers)
        assert bad_cursor.status_code == 400
        assert bad_cursor.json()["detail"] == "invalid_cursor"
        bad_kind = client.get("/advisor/activity?kinds=payment,gossip", headers=auth_headers)
        assert bad_kind.status_code == 400
        assert bad_kind.json()["detail"] == "unknown_kind"


def test_activity_clamps_the_limit(
    as_advisor: None, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _load(session: Any, **kwargs: Any) -> list[ActivityEvent]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(advisor_module, "load_advisor_activity", _load)
    with TestClient(fastapi_app) as client:
        assert client.get("/advisor/activity?limit=9999", headers=auth_headers).status_code == 200
    assert captured["limit"] == 100


def test_money_envelope_and_filters(
    as_advisor: None, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import InvoiceStatus
    from app.services.advisor_money import MoneyRow, MoneySummaryRow

    captured: dict[str, Any] = {}
    row = MoneyRow(
        id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        client_name="Margaret Chen",
        itinerary_id=uuid.uuid4(),
        itinerary_title="Kyoto",
        label="Deposit",
        status=InvoiceStatus.issued,
        currency="USD",
        total=Decimal("1500"),
        settled=Decimal("0"),
        issued_at=_NOW,
        due_at=None,
        created_at=_NOW,
    )
    summary = MoneySummaryRow(
        currency="USD",
        invoiced=Decimal("1500"),
        paid=Decimal("0"),
        outstanding=Decimal("1500"),
    )

    async def _load(session: Any, **kwargs: Any) -> tuple[list[MoneyRow], list[MoneySummaryRow]]:
        captured.update(kwargs)
        return [row], [summary]

    monkeypatch.setattr(advisor_module, "load_advisor_money", _load)
    with TestClient(fastapi_app) as client:
        body = client.get("/advisor/money?status=issued", headers=auth_headers).json()
    assert captured["status"] is not None
    assert body["invoices"][0]["client_name"] == "Margaret Chen"
    assert body["summary"][0]["outstanding"] == "1500"
    assert body["next_cursor"] is None  # short page → the end
