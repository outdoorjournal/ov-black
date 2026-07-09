"""The advisor SSE feed (Wave F) — frame encoding, tick math, stream lifecycle.

The generator's async-loop behavior (hello → activity → heartbeat → bye) runs
against a stubbed sessionmaker with feed_poll_seconds shrunk to ~0 so the
whole lifecycle plays out in milliseconds. The router test scripts the
generator entirely (test_agent_router.py's pattern) and asserts headers.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.config import get_settings
from app.main import app as fastapi_app
from app.routers import advisor as advisor_module
from app.services.activity import ActivityEvent
from app.services.feed import event_frame, sse_encode, stream_advisor_feed
from fastapi.testclient import TestClient

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
_ADVISOR = uuid.uuid4()


def _event(at: datetime, source_id: str = "1") -> ActivityEvent:
    return ActivityEvent(
        kind="payment",
        at=at,
        source_id=source_id,
        client_id=uuid.uuid4(),
        itinerary_id=uuid.uuid4(),
        itinerary_title="Kyoto",
        actor_kind=None,
        title="Deposit",
        op="succeeded",
        status_before=None,
        status_after=None,
        amount=Decimal("12.50"),
        currency="USD",
        ref_id=None,
    )


# ── pure: the wire format ────────────────────────────────────────────────────


def test_sse_encode_matches_the_agent_stream_format() -> None:
    frame = sse_encode({"type": "heartbeat", "at": "x"})
    assert frame == b'data: {"type":"heartbeat","at":"x"}\n\n'


def test_event_frame_projects_and_stamps_cursor() -> None:
    e = _event(_NOW)
    frame = event_frame(e)
    assert frame["type"] == "activity"
    assert frame["v"] == 1
    assert frame["cursor"] == _NOW.isoformat()
    assert frame["event"]["kind"] == "payment"
    assert frame["event"]["amount"] == "12.50"
    # Structural redaction — the frame carries only the projection keys.
    assert "content" not in frame["event"]
    assert "before" not in frame["event"]


# ── the generator lifecycle (stubbed DB, sub-ms ticks) ───────────────────────


class _StubSession:
    def __init__(self) -> None:  # pragma: no cover - trivial
        pass

    async def __aenter__(self) -> _StubSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _stub_sessionmaker() -> Any:
    return lambda: _StubSession()


@pytest.fixture()
def fast_settings() -> Any:
    settings = get_settings().model_copy(
        update={
            "feed_poll_seconds": 0.001,
            "feed_heartbeat_seconds": 0.001,
            "feed_max_stream_seconds": 60,
        }
    )
    return settings


async def test_stream_says_hello_heartbeats_and_emits(
    fast_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First tick returns one event, later ticks nothing — the stream should
    open with hello(cursor), emit the activity frame, then heartbeat."""
    calls = {"n": 0}

    async def _fake_load(session: Any, **kwargs: Any) -> list[ActivityEvent]:
        calls["n"] += 1
        assert kwargs["after"] is not None  # always ascending tick mode
        if calls["n"] == 1:
            return [_event(_NOW + timedelta(seconds=1))]
        return []

    monkeypatch.setattr("app.services.feed.load_advisor_activity", _fake_load)

    frames: list[dict[str, Any]] = []
    stream = stream_advisor_feed(
        _stub_sessionmaker(), advisor_id=_ADVISOR, settings=fast_settings, cursor=_NOW
    )
    async for chunk in stream:
        frames.append(json.loads(chunk.removeprefix(b"data: ").strip()))
        if len(frames) >= 3:
            await stream.aclose()
            break

    assert frames[0]["type"] == "hello"
    assert frames[0]["cursor"] == _NOW.isoformat()
    assert frames[1]["type"] == "activity"
    assert frames[1]["event"]["title"] == "Deposit"
    assert frames[2]["type"] == "heartbeat"
    # The watermark advanced: tick 2+ was called with the event's at.
    assert calls["n"] >= 2


async def test_stream_closes_with_bye_at_token_expiry(
    fast_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_load(session: Any, **kwargs: Any) -> list[ActivityEvent]:
        return []

    monkeypatch.setattr("app.services.feed.load_advisor_activity", _fake_load)
    # Token already expired → lifetime clamps to zero → hello then bye.
    stream = stream_advisor_feed(
        _stub_sessionmaker(),
        advisor_id=_ADVISOR,
        settings=fast_settings,
        token_exp=datetime.now(UTC) - timedelta(seconds=5),
    )
    frames = [json.loads(chunk.removeprefix(b"data: ").strip()) async for chunk in stream]
    assert [f["type"] for f in frames] == ["hello", "bye"]
    assert frames[-1]["reason"] == "reauth"


# ── router: headers + auth + scripted body ───────────────────────────────────


@pytest.fixture()
def as_advisor() -> Iterator[None]:
    async def _dep() -> AuthenticatedUser:
        return AuthenticatedUser(
            sub=str(_ADVISOR),
            email="advisor@example.com",
            role="authenticated",
            claims={"sub": str(_ADVISOR), "exp": int(datetime.now(UTC).timestamp()) + 3600},
        )

    fastapi_app.dependency_overrides[require_advisor] = _dep
    try:
        yield None
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)


@pytest.fixture()
def auth_headers(make_token: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(_ADVISOR))}"}


def test_feed_route_streams_scripted_frames(
    as_advisor: None, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _scripted(*args: Any, **kwargs: Any) -> Any:
        yield sse_encode({"type": "hello", "v": 1, "cursor": "c", "heartbeat_ms": 1})
        yield sse_encode({"type": "bye", "reason": "reauth"})

    monkeypatch.setattr(advisor_module, "stream_advisor_feed", _scripted)
    with (
        TestClient(fastapi_app) as client,
        client.stream("GET", "/advisor/feed", headers=auth_headers) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"
        body = b"".join(response.iter_bytes())
    assert b'"type":"hello"' in body
    assert b'"type":"bye"' in body


def test_feed_route_rejects_malformed_cursor(
    as_advisor: None, auth_headers: dict[str, str]
) -> None:
    with TestClient(fastapi_app) as client:
        response = client.get("/advisor/feed?cursor=not-a-date", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cursor"


def test_feed_route_403_for_non_advisors(
    auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    async def _deny() -> AuthenticatedUser:
        raise HTTPException(status_code=403, detail="advisor_only")

    fastapi_app.dependency_overrides[require_advisor] = _deny
    try:
        with TestClient(fastapi_app) as client:
            response = client.get("/advisor/feed", headers=auth_headers)
        assert response.status_code == 403
    finally:
        fastapi_app.dependency_overrides.pop(require_advisor, None)
