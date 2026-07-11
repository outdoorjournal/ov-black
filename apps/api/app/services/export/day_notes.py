"""Per-day trip notes: LLM generation, deterministic fallback, and auto-fill.

The export's "what you should bring / tips" section. Three authorship sources
(mirroring migration 0045): ``advisor`` rows are hand-written and NEVER
auto-touched; ``llm`` rows come from one Bedrock ``converse`` call per export
covering every stale/missing day (cross-day context — timezone shifts, late
arrivals — is exactly what good day notes need); ``fallback`` rows come from
the deterministic rules below when Bedrock is disabled or fails. An export
must always succeed — every failure path lands on the fallback, never a 5xx.

REDACTION GUARANTEE: the prompt builder accepts only the export dataclasses
built in :mod:`app.services.export.grouping` from Node rows. This module must
never import traveler-context / dossier / OSINT / profile-fact code, and it
never logs prompt or response content — only counts, source, and timing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

import anyio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import DayNotesSource, ItineraryDayNotes
from app.services.export.grouping import ExportDay, ExportTrip

logger = logging.getLogger("ov_black.export.day_notes")

# Bump when the prompt or fallback rules change materially — invalidates every
# generated (non-advisor) row on its next export.
PROMPT_VERSION = 1

_MAX_BULLETS = 5
_MAX_BULLET_CHARS = 200


class DayNotesError(Exception):
    """Domain error for the Bedrock day-notes call; callers fall back."""


class DayNotesClient(Protocol):
    """Seam for the one-shot notes generation call."""

    async def generate(self, prompt: str) -> str: ...


class Boto3DayNotesClient:
    """Real client backed by ``boto3.client('bedrock-runtime')`` ``converse``.

    Lazy on both import and construction (the ``app.agent.bedrock`` idiom) so
    AWS-free lanes never touch credentials; the sync SDK call runs in a worker
    thread via ``anyio.to_thread.run_sync``.
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._settings.aws_region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=25,
                    retries={"max_attempts": 1},
                ),
            )
        return self._client

    async def generate(self, prompt: str) -> str:
        client = self._ensure_client()
        model_id = self._settings.export_day_notes_model_id

        def _converse() -> Any:
            return client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 2000, "temperature": 0.4},
            )

        try:
            response = await anyio.to_thread.run_sync(_converse)
        except Exception as exc:  # noqa: BLE001 — any botocore error → fallback
            raise DayNotesError(exc.__class__.__name__) from exc
        try:
            text = response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DayNotesError("malformed_response") from exc
        if not isinstance(text, str):
            raise DayNotesError("malformed_response")
        return text


class MockDayNotesClient:
    """Scripted client for tests. Records prompts; yields canned responses."""

    def __init__(
        self,
        responses: Sequence[str] | None = None,
        *,
        raise_on_generate: BaseException | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise = raise_on_generate
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._raise is not None:
            raise self._raise
        if not self._responses:
            return "{}"
        index = min(len(self.prompts), len(self._responses)) - 1
        return self._responses[index]


# ── Hashing ──────────────────────────────────────────────────────────────────


def compute_nodes_hash(day: ExportDay, prev_tz_offset_minutes: int | None) -> str:
    """Fingerprint of the day's export-visible content.

    Covers every field the notes could react to, plus the PREVIOUS day's tz
    offset (a zone shift is a cross-day fact) and :data:`PROMPT_VERSION`.
    """
    payload = {
        "v": PROMPT_VERSION,
        "prev_tz": prev_tz_offset_minutes,
        "tz": day.tz_offset_minutes,
        "night": day.night_hotel,
        "items": [
            [
                item.type,
                item.title,
                item.start_local.isoformat() if item.start_local else None,
                item.duration_minutes,
                item.location,
                item.status,
                item.altitude_m,
                item.tz_offset_minutes,
            ]
            for item in day.items
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Prompt + parsing ─────────────────────────────────────────────────────────


def _day_lines(day: ExportDay) -> str:
    lines = [f"{day.label} ({day.day_date.isoformat()}, UTC offset min: {day.tz_offset_minutes}):"]
    for item in day.items:
        when = item.start_local.strftime("%H:%M") if item.start_local else "all day"
        bits = [f"  - {when} [{item.type}] {item.title}"]
        if item.location:
            bits.append(f"at {item.location}")
        if item.duration_minutes:
            bits.append(f"({item.duration_minutes} min)")
        if item.altitude_m:
            bits.append(f"altitude {item.altitude_m}m")
        if item.journey:
            bits.append(
                f"— day {item.journey.index} of {item.journey.total} of {item.journey.parent_title}"
            )
        lines.append(" ".join(bits))
    if day.night_hotel:
        lines.append(f"  Night: {day.night_hotel}")
    return "\n".join(lines)


def build_day_notes_prompt(
    days: Sequence[ExportDay],
    target_dates: Sequence[date],
    *,
    title: str,
    brief: str | None,
) -> str:
    """The single converse prompt. Accepts ONLY export dataclasses — that
    signature (not a convention) is what keeps dossier/OSINT/profile content
    out of the model's view."""
    targets = ", ".join(d.isoformat() for d in target_dates)
    schedule = "\n\n".join(_day_lines(day) for day in days)
    goal = f" Trip goal: {brief}." if brief else ""
    return (
        "You are the Outdoor Voyage concierge preparing the printed itinerary "
        f"for the trip “{title}”.{goal}\n\n"
        "Full day-by-day schedule:\n\n"
        f"{schedule}\n\n"
        f"Write practical day notes for these dates only: {targets}.\n"
        "For each date give:\n"
        '- "bring": 3-5 short, specific items to carry that day (driven by the '
        "day's activities, weather-agnostic).\n"
        '- "tips": 1-3 short practical tips (time-zone changes and jet lag, '
        "early starts, hotel changes / packing up, long walks, altitude, "
        "pacing). Mention a time-zone change on the day it happens.\n"
        "Plain factual tone; no marketing language.\n\n"
        "Respond with ONLY a JSON object keyed by ISO date, e.g. "
        '{"2026-06-01": {"bring": ["..."], "tips": ["..."]}}. No other text.'
    )


def _clean_bullets(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    bullets = [b.strip()[:_MAX_BULLET_CHARS] for b in raw if isinstance(b, str) and b.strip()]
    return bullets[:_MAX_BULLETS]


def parse_llm_notes(text: str, target_dates: Sequence[date]) -> dict[date, dict[str, Any]] | None:
    """Parse the model's JSON into ``{date: {"bring": [...], "tips": [...]}}``.

    Tolerates prose around the JSON (first ``{...}`` span). Returns ``None``
    when nothing usable parses — the caller falls back deterministically.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        decoded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    out: dict[date, dict[str, Any]] = {}
    for target in target_dates:
        entry = decoded.get(target.isoformat())
        if not isinstance(entry, dict):
            continue
        bring = _clean_bullets(entry.get("bring"))
        tips = _clean_bullets(entry.get("tips"))
        if bring or tips:
            out[target] = {"bring": bring, "tips": tips}
    return out or None


# ── Deterministic fallback ───────────────────────────────────────────────────


def fallback_notes(
    day: ExportDay,
    prev_day: ExportDay | None,
) -> dict[str, Any]:
    """Rule-based notes when the LLM lane is unavailable. Small on purpose."""
    bring: list[str] = []
    tips: list[str] = []

    prev_tz = prev_day.tz_offset_minutes if prev_day is not None else None
    if (
        prev_tz is not None
        and day.tz_offset_minutes is not None
        and prev_tz != day.tz_offset_minutes
    ):
        delta_h = (day.tz_offset_minutes - prev_tz) / 60
        sign = "+" if delta_h > 0 else "−"
        hours = abs(delta_h)
        hours_text = f"{hours:g}"
        tips.append(f"You change time zones today ({sign}{hours_text}h) — expect some jet lag.")

    types = {item.type for item in day.items}
    if "flight" in types:
        bring.append("Travel documents and chargers")
    if "boat" in types:
        bring.append("A waterproof layer")
    if any(item.type == "walk" and (item.duration_minutes or 0) >= 90 for item in day.items):
        bring.append("Comfortable shoes and water")
    if any((item.altitude_m or 0) >= 2000 for item in day.items):
        bring.append("Sun protection — and keep hydrated at altitude")
    if "meal" not in types:
        tips.append("No meals are scheduled — keep snacks handy.")

    timed = [item.start_local for item in day.items if item.start_local is not None]
    if timed and min(timed).hour < 8:
        tips.append("Early start — set an alarm the night before.")
    if (
        prev_day is not None
        and day.night_hotel is not None
        and prev_day.night_hotel is not None
        and day.night_hotel != prev_day.night_hotel
    ):
        tips.append(
            f"You change hotels today — pack up before you head out ({day.night_hotel} tonight)."
        )

    return {"bring": bring[:_MAX_BULLETS], "tips": tips[:_MAX_BULLETS]}


# ── Auto-fill (the export path) ──────────────────────────────────────────────


async def _load_rows(
    session: AsyncSession, itinerary_id: uuid.UUID
) -> dict[date, ItineraryDayNotes]:
    rows = (
        (
            await session.execute(
                select(ItineraryDayNotes).where(ItineraryDayNotes.itinerary_id == itinerary_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.day_date: row for row in rows}


async def _upsert_row(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    day_date: date,
    *,
    source: str,
    nodes_hash: str | None,
    content: dict[str, Any],
    updated_by: uuid.UUID | None = None,
) -> None:
    stmt = pg_insert(ItineraryDayNotes).values(
        itinerary_id=itinerary_id,
        day_date=day_date,
        source=source,
        nodes_hash=nodes_hash,
        content=content,
        updated_by=updated_by,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ItineraryDayNotes.itinerary_id, ItineraryDayNotes.day_date],
        set_={
            "source": stmt.excluded.source,
            "nodes_hash": stmt.excluded.nodes_hash,
            "content": stmt.excluded.content,
            "updated_by": stmt.excluded.updated_by,
            "generated_at": stmt.excluded.generated_at,
        },
    )
    await session.execute(stmt)


async def _generate(
    trip: ExportTrip,
    targets: list[date],
    *,
    client: DayNotesClient,
) -> dict[date, dict[str, Any]] | None:
    """One LLM call for all target days; ``None`` on any failure."""
    prompt = build_day_notes_prompt(trip.days, targets, title=trip.title, brief=trip.brief)
    try:
        text = await client.generate(prompt)
    except DayNotesError as exc:
        logger.warning("export.day_notes.llm_failed", extra={"reason": str(exc)})
        return None
    return parse_llm_notes(text, targets)


async def ensure_day_notes(
    session: AsyncSession,
    itinerary_id: uuid.UUID,
    trip: ExportTrip,
    *,
    settings: Settings | None = None,
    client: DayNotesClient | None = None,
    force_regenerate: bool = False,
    only_dates: set[date] | None = None,
) -> dict[date, dict[str, Any]]:
    """Return ``{day: content}`` for every trip day, auto-filling the store.

    Advisor rows are used verbatim and never regenerated. Generated rows with
    a fresh ``nodes_hash`` are cache hits (unless ``force_regenerate``, the
    manual advisor invoke). Everything else gets one LLM call — or the
    deterministic fallback when the lane is disabled, the call fails, or the
    response doesn't parse. ``only_dates`` restricts which days are (re)filled.
    """
    settings = settings or get_settings()
    existing = await _load_rows(session, itinerary_id)

    hashes: dict[date, str] = {}
    stale: list[date] = []
    result: dict[date, dict[str, Any]] = {}
    prev: ExportDay | None = None
    for day in trip.days:
        prev_tz = prev.tz_offset_minutes if prev is not None else None
        hashes[day.day_date] = compute_nodes_hash(day, prev_tz)
        prev = day

        row = existing.get(day.day_date)
        if row is not None and row.source == DayNotesSource.advisor.value:
            result[day.day_date] = dict(row.content)
            continue
        if only_dates is not None and day.day_date not in only_dates:
            if row is not None:
                result[day.day_date] = dict(row.content)
            continue
        if row is not None and not force_regenerate and row.nodes_hash == hashes[day.day_date]:
            result[day.day_date] = dict(row.content)
            continue
        stale.append(day.day_date)

    if not stale:
        return result

    started = time.monotonic()
    generated: dict[date, dict[str, Any]] | None = None
    if settings.export_day_notes_enabled:
        llm_client = client if client is not None else Boto3DayNotesClient(settings=settings)
        generated = await _generate(trip, stale, client=llm_client)

    days_by_date = {day.day_date: day for day in trip.days}
    day_list = list(trip.days)
    for target in stale:
        content = generated.get(target) if generated is not None else None
        if content is not None:
            source = DayNotesSource.llm.value
        else:
            day = days_by_date[target]
            index = day_list.index(day)
            content = fallback_notes(day, day_list[index - 1] if index > 0 else None)
            source = DayNotesSource.fallback.value
        await _upsert_row(
            session,
            itinerary_id,
            target,
            source=source,
            nodes_hash=hashes[target],
            content=content,
        )
        result[target] = content

    logger.info(
        "export.day_notes.filled",
        extra={
            "days": len(trip.days),
            "generated": len(stale),
            "source": "llm" if generated is not None else "fallback",
            "ms": int((time.monotonic() - started) * 1000),
        },
    )
    return result
