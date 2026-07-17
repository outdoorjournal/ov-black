"""Itinerary export HTTP surface — PDF / XLSX download + day-notes CRUD.

- ``GET  /itinerary/{id}/export?format=pdf|xlsx`` — download the trip (trunk
  or any fork the caller can read). Auto-fills missing/stale day notes.
- ``GET  /itinerary/{id}/day-notes`` — list per-day notes (readable).
- ``PUT  /itinerary/{id}/day-notes/{day}`` — advisor upsert (source=advisor).
- ``DELETE /itinerary/{id}/day-notes/{day}`` — advisor delete (reverts to auto).
- ``POST /itinerary/{id}/day-notes/generate`` — advisor manual AI regenerate.

Read/mutation gates reuse the itinerary router's ``assert_itinerary_readable``
and the shared ``require_advisor`` guard. Files are generated on the fly and
streamed back with a ``Content-Disposition`` attachment header — small enough
that S3 staging isn't warranted.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_user
from app.auth_guards import require_advisor
from app.config import get_settings
from app.db import get_session
from app.models import DayNotesSource, Itinerary, ItineraryDayNotes
from app.routers.itineraries import assert_itinerary_readable
from app.services.export.day_notes import ensure_day_notes
from app.services.export.grouping import load_export_trip
from app.services.export.pdf import build_pdf
from app.services.export.xlsx import build_xlsx

router = APIRouter(prefix="/itinerary", tags=["itinerary"])

_PDF_MEDIA = "application/pdf"
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _load_readable_itinerary(
    session: AsyncSession, user: AuthenticatedUser, itinerary_id: uuid.UUID
) -> Itinerary:
    itinerary = await session.get(Itinerary, itinerary_id)
    if itinerary is None:
        raise HTTPException(status_code=404, detail="not_found")
    await assert_itinerary_readable(session, user, itinerary)
    return itinerary


def _slug(title: str) -> str:
    """ASCII slug for the fallback ``filename=`` (safe across old clients)."""
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-")
    return slug or "itinerary"


def _content_disposition(title: str, anchor: date | None, ext: str) -> str:
    stamp = (anchor or date.today()).isoformat()
    ascii_name = f"{_slug(title)}-{stamp}.{ext}"
    # A UTF-8 filename* for modern clients; the ASCII filename= as fallback.
    utf8_name = quote(f"{title} {stamp}.{ext}")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


@router.get(
    "/{itinerary_id}/export",
    summary="Download the itinerary as a PDF or XLSX.",
    response_class=Response,
    responses={200: {"content": {_PDF_MEDIA: {}, _XLSX_MEDIA: {}}}},
)
async def export_itinerary_endpoint(
    itinerary_id: uuid.UUID,
    format: str = Query(..., pattern="^(pdf|xlsx)$"),
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    itinerary = await _load_readable_itinerary(session, user, itinerary_id)
    trip = await load_export_trip(session, itinerary)

    anchor = itinerary.date_start or itinerary.days_anchor
    if format == "xlsx":
        data = build_xlsx(trip)
        # No day notes needed for the spreadsheet.
        return Response(
            content=data,
            media_type=_XLSX_MEDIA,
            headers={"Content-Disposition": _content_disposition(trip.title, anchor, "xlsx")},
        )

    notes = await ensure_day_notes(session, itinerary_id, trip)
    await session.commit()  # persist any freshly generated/cached day-notes rows
    pdf = build_pdf(trip, notes)
    return Response(
        content=bytes(pdf.output()),
        media_type=_PDF_MEDIA,
        headers={"Content-Disposition": _content_disposition(trip.title, anchor, "pdf")},
    )


# ── Day-notes CRUD (advisor-authored) ────────────────────────────────────────


class DayNoteContent(BaseModel):
    bring: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)


class DayNoteResponse(BaseModel):
    day_date: date
    source: str
    content: DayNoteContent
    generated_at: str


class DayNotesListResponse(BaseModel):
    itinerary_id: uuid.UUID
    notes: list[DayNoteResponse]


class GenerateDayNotesRequest(BaseModel):
    days: list[date] | None = Field(
        default=None,
        description="Restrict regeneration to these dates; omit for all days.",
    )


def _to_response(row: ItineraryDayNotes) -> DayNoteResponse:
    raw = row.content if isinstance(row.content, dict) else {}
    return DayNoteResponse(
        day_date=row.day_date,
        source=row.source,
        content=DayNoteContent(
            bring=[b for b in raw.get("bring", []) if isinstance(b, str)],
            tips=[t for t in raw.get("tips", []) if isinstance(t, str)],
        ),
        generated_at=row.generated_at.isoformat(),
    )


@router.get(
    "/{itinerary_id}/day-notes",
    response_model=DayNotesListResponse,
    summary="List the itinerary's per-day notes.",
)
async def list_day_notes_endpoint(
    itinerary_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> DayNotesListResponse:
    await _load_readable_itinerary(session, user, itinerary_id)
    rows = (
        (
            await session.execute(
                select(ItineraryDayNotes)
                .where(ItineraryDayNotes.itinerary_id == itinerary_id)
                .order_by(ItineraryDayNotes.day_date)
            )
        )
        .scalars()
        .all()
    )
    return DayNotesListResponse(itinerary_id=itinerary_id, notes=[_to_response(r) for r in rows])


@router.put(
    "/{itinerary_id}/day-notes/{day_date}",
    response_model=DayNoteResponse,
    summary="Advisor: upsert hand-written notes for one day.",
)
async def put_day_note_endpoint(
    itinerary_id: uuid.UUID,
    day_date: date,
    payload: DayNoteContent,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DayNoteResponse:
    await _load_readable_itinerary(session, user, itinerary_id)
    updated_by = uuid.UUID(user.sub) if user.sub else None
    content = {"bring": payload.bring, "tips": payload.tips}
    stmt = pg_insert(ItineraryDayNotes).values(
        itinerary_id=itinerary_id,
        day_date=day_date,
        source=DayNotesSource.advisor.value,
        nodes_hash=None,
        content=content,
        updated_by=updated_by,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=[ItineraryDayNotes.itinerary_id, ItineraryDayNotes.day_date],
        set_={
            "source": DayNotesSource.advisor.value,
            "nodes_hash": None,
            "content": content,
            "updated_by": updated_by,
            "generated_at": stmt.excluded.generated_at,
        },
    ).returning(ItineraryDayNotes)
    row = (await session.execute(upsert)).scalar_one()
    await session.commit()
    return _to_response(row)


@router.delete(
    "/{itinerary_id}/day-notes/{day_date}",
    status_code=204,
    summary="Advisor: delete a day's notes (reverts to auto-fill).",
)
async def delete_day_note_endpoint(
    itinerary_id: uuid.UUID,
    day_date: date,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _load_readable_itinerary(session, user, itinerary_id)
    await session.execute(
        delete(ItineraryDayNotes).where(
            ItineraryDayNotes.itinerary_id == itinerary_id,
            ItineraryDayNotes.day_date == day_date,
        )
    )
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/{itinerary_id}/day-notes/generate",
    response_model=DayNotesListResponse,
    summary="Advisor: (re)generate day notes with AI.",
)
async def generate_day_notes_endpoint(
    itinerary_id: uuid.UUID,
    payload: GenerateDayNotesRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DayNotesListResponse:
    settings = get_settings()
    if not settings.export_day_notes_enabled:
        # A manual AI invoke with the LLM lane off isn't worth the fallback.
        raise HTTPException(status_code=409, detail="day_notes_disabled")
    itinerary = await _load_readable_itinerary(session, user, itinerary_id)
    trip = await load_export_trip(session, itinerary)
    only = set(payload.days) if payload.days else None
    await ensure_day_notes(session, itinerary_id, trip, force_regenerate=True, only_dates=only)
    await session.commit()
    rows = (
        (
            await session.execute(
                select(ItineraryDayNotes)
                .where(ItineraryDayNotes.itinerary_id == itinerary_id)
                .order_by(ItineraryDayNotes.day_date)
            )
        )
        .scalars()
        .all()
    )
    return DayNotesListResponse(itinerary_id=itinerary_id, notes=[_to_response(r) for r in rows])
