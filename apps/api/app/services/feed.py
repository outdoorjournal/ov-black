"""Advisor live feed — poll-to-push SSE over the activity projection (Wave F).

``GET /advisor/feed`` holds one streaming response per connected advisor. The
generator ticks every ``feed_poll_seconds``: a short DB session (the
``stream_turn`` sessionmaker pattern — never a request-scoped session held
across the stream) runs :func:`app.services.activity.load_advisor_activity`
in ascending ``after=`` mode and emits each new event as an ``activity``
frame. No broker, no LISTEN/NOTIFY, no server-side connection registry — the
server holds NOTHING across connections, so task restarts, deploys and
``--reload`` all reduce to "the client reconnects and resumes from its
cursor". (Upgrading liveness later = swap the tick trigger; the wire contract
doesn't move.)

Frame contract (v1, ``data:``-only JSON like the agent turn stream):

- ``{"type":"hello","v":1,"cursor":"<iso>","heartbeat_ms":N}`` — on connect;
  echoes the resume cursor the server will poll from.
- ``{"type":"activity","v":1,"event":{…ActivityEventOut…},"cursor":"<iso>"}``
  — one per new event, oldest-first; ``cursor`` is the client's new resume
  watermark (the event's ``at``).
- ``{"type":"heartbeat","at":"<iso>"}`` — after ``feed_heartbeat_seconds``
  idle; keeps the ALB (120s idle timeout) from cutting the stream.
- ``{"type":"bye","reason":"reauth"}`` — server-initiated close at
  ``min(JWT exp, feed_max_stream_seconds)``; the browser reconnects with a
  fresh token.

Redaction: frames carry exactly the activity projection (ids / kinds / titles
/ timestamps / money amounts per the authed-response precedent) — never
message content, turn text, or fact text. Nothing logged beyond counts.

Same-instant stragglers: the watermark advances to the newest emitted ``at``
and the next tick reads strictly greater — an event landing later with an
identical timestamp can be missed on the wire. Accepted (frames are additive
UI, the reconnect snapshot heals) — documented so nobody "fixes" it into a
duplicate storm.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.services.activity import ActivityEvent, load_advisor_activity


def sse_encode(event: dict[str, Any]) -> bytes:
    """``data: <compact json>\\n\\n`` — the agent stream's exact wire format."""
    payload = json.dumps(event, separators=(",", ":"), default=str).encode("utf-8")
    return b"data: " + payload + b"\n\n"


def event_frame(event: ActivityEvent) -> dict[str, Any]:
    """One activity event as its v1 frame (cursor = the event's own ``at``)."""
    return {
        "type": "activity",
        "v": 1,
        "event": {
            "kind": event.kind,
            "at": event.at.isoformat(),
            "source_id": event.source_id,
            "client_id": str(event.client_id),
            "itinerary_id": str(event.itinerary_id) if event.itinerary_id else None,
            "itinerary_title": event.itinerary_title,
            "actor_kind": event.actor_kind,
            "title": event.title,
            "op": event.op,
            "status_before": event.status_before,
            "status_after": event.status_after,
            "amount": str(event.amount) if event.amount is not None else None,
            "currency": event.currency,
            "ref_id": str(event.ref_id) if event.ref_id else None,
        },
        "cursor": event.at.isoformat(),
    }


async def collect_tick(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    watermark: datetime,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], datetime]:
    """One poll: frames for everything since ``watermark``, plus the new watermark.

    Transport-agnostic on purpose — the SSE generator drives it, and a plain
    JSON ``/feed/since`` fallback could reuse it verbatim if ALB SSE ever
    misbehaves.
    """
    events = await load_advisor_activity(
        session, advisor_id=advisor_id, limit=limit, after=watermark
    )
    frames = [event_frame(e) for e in events]
    new_watermark = max((e.at for e in events), default=watermark)
    return frames, new_watermark


async def stream_advisor_feed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    advisor_id: uuid.UUID,
    settings: Settings,
    cursor: datetime | None = None,
    token_exp: datetime | None = None,
) -> AsyncIterator[bytes]:
    """The infinite (lifetime-capped) advisor feed generator.

    Auth happened at request open; ``token_exp`` caps the stream so a revoked
    or expired JWT can't hold a live feed forever. Each tick opens its own
    short DB session — a dead client surfaces as a write error on ``yield``
    and the generator just exits (nothing to clean up).
    """
    started = datetime.now(UTC)
    watermark = cursor or started
    deadline = started + _lifetime(settings, started, token_exp)

    yield sse_encode(
        {
            "type": "hello",
            "v": 1,
            "cursor": watermark.isoformat(),
            "heartbeat_ms": int(settings.feed_heartbeat_seconds * 1000),
        }
    )

    last_sent = datetime.now(UTC)
    while True:
        now = datetime.now(UTC)
        if now >= deadline:
            yield sse_encode({"type": "bye", "reason": "reauth"})
            return

        async with session_factory() as db:
            frames, watermark = await collect_tick(db, advisor_id=advisor_id, watermark=watermark)
        for frame in frames:
            yield sse_encode(frame)
        if frames:
            last_sent = datetime.now(UTC)
        elif (datetime.now(UTC) - last_sent).total_seconds() >= settings.feed_heartbeat_seconds:
            yield sse_encode({"type": "heartbeat", "at": datetime.now(UTC).isoformat()})
            last_sent = datetime.now(UTC)

        await asyncio.sleep(settings.feed_poll_seconds)


def _lifetime(settings: Settings, started: datetime, token_exp: datetime | None) -> timedelta:
    cap = timedelta(seconds=settings.feed_max_stream_seconds)
    if token_exp is not None:
        until_exp = token_exp - started
        if until_exp < cap:
            return max(until_exp, timedelta(seconds=0))
    return cap
