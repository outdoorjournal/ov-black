"""Advisor-facing roster of itineraries — one row per official trunk.

This is the plural-namespace counterpart to ``/itinerary/{id}`` (singular,
shared between advisor + traveler) and ``/me/itineraries`` (traveler's
own, lean shape). Returns a rich row that embeds the owning client so
the Command Center can render the entire roster in a dense table without
N+1 lookups.

Wave F: the envelope gains keyset paging (``next_cursor`` + ``total``),
substring search (``q=`` over title OR client name), status / client filters,
and sort params — and ``needs_attention`` is real: one awareness pass per page
(grouped by itinerary, never per-row) lights the rows whose trip carries an
open-state signal.

Gated by :func:`require_advisor`. Scope is the calling advisor's clients
(``clients.owner_id = advisor_id``) — orphan itineraries with no client
(``itineraries.client_id IS NULL``) are intentionally excluded; the
advisor-facing view never wants those.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import and_, func, or_, select

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.models import Client, Itinerary
from app.routers.clients import _advisor_id, _escape_like
from app.services.awareness import ACTIONABLE_KINDS, load_advisor_attention
from app.services.display_status import DisplayStatus, display_status_expr
from app.services.pagination import clamp_limit, encode_cursor, require_cursor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.advisor_itineraries")

router = APIRouter(prefix="/itineraries", tags=["itineraries"])


class AdvisorItineraryClient(BaseModel):
    """Embedded client shape for the advisor roster row."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr


class AdvisorItinerarySummary(BaseModel):
    """Row shape for the advisor roster of itineraries."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    title: str
    # Derived trunk lifecycle bucket (in_studio / with_traveler / approved) —
    # computed in SQL from the trip's nodes, never stored.
    status: DisplayStatus
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    client: AdvisorItineraryClient
    # True when the trip carries an open-state awareness signal (changes
    # requested, unread messages, expiring offer, unpaid invoice, unconfirmed
    # booking) — the roster's brand dot. Wired for real in Wave F.
    needs_attention: bool = False


class AdvisorItinerariesResponse(BaseModel):
    """Envelope for ``GET /itineraries`` (advisor)."""

    model_config = ConfigDict(extra="forbid")

    itineraries: list[AdvisorItinerarySummary]
    next_cursor: str | None = None
    total: int = 0


_SORT_COLS = {
    "updated_at": Itinerary.updated_at,
    "created_at": Itinerary.created_at,
    "title": Itinerary.title,
}


@router.get(
    "",
    response_model=AdvisorItinerariesResponse,
    summary="Search/page every itinerary across the calling advisor's clients.",
)
async def list_advisor_itineraries_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    cursor: str | None = None,
    q: str | None = None,
    status: DisplayStatus | None = None,
    client_id: uuid.UUID | None = None,
    sort: Literal["updated_at", "created_at", "title"] = "updated_at",
    order: Literal["asc", "desc"] | None = None,
) -> AdvisorItinerariesResponse:
    advisor_id = _advisor_id(user)
    page_limit = clamp_limit(limit)
    direction = order or ("asc" if sort == "title" else "desc")
    sort_col = _SORT_COLS[sort]

    # Trunks only — forks are private working copies, not roster rows.
    filters: list[Any] = [Client.owner_id == advisor_id, Itinerary.forked_from_id.is_(None)]
    if q:
        needle = f"%{_escape_like(q)}%"
        filters.append(
            or_(
                Itinerary.title.ilike(needle, escape="\\"),
                Client.full_name.ilike(needle, escape="\\"),
            )
        )
    if status is not None:
        filters.append(display_status_expr() == status.value)
    if client_id is not None:
        filters.append(Client.id == client_id)

    total = int(
        (
            await session.execute(
                select(func.count(Itinerary.id))
                .join(Client, Client.id == Itinerary.client_id)
                .where(*filters)
            )
        ).scalar_one()
    )

    stmt = (
        select(Itinerary, Client, display_status_expr())
        .join(Client, Client.id == Itinerary.client_id)
        .where(*filters)
    )
    payload = require_cursor(cursor)
    if payload is not None:
        cur_id = uuid.UUID(str(payload["id"]))
        raw_v = str(payload["v"])
        cur_v: Any = raw_v if sort == "title" else datetime.fromisoformat(raw_v)
        if direction == "desc":
            stmt = stmt.where(or_(sort_col < cur_v, and_(sort_col == cur_v, Itinerary.id > cur_id)))
        else:
            stmt = stmt.where(or_(sort_col > cur_v, and_(sort_col == cur_v, Itinerary.id > cur_id)))
    ordered = sort_col.desc() if direction == "desc" else sort_col.asc()
    stmt = stmt.order_by(ordered, Itinerary.id.asc()).limit(page_limit)
    rows = (await session.execute(stmt)).all()

    # One awareness pass for the page: itineraries carrying an open-state
    # signal get the dot. Grouped, never per-row (R2 in the plan).
    attention_itineraries: set[uuid.UUID] = set()
    if rows:
        for summary in await load_advisor_attention(session, advisor_id=advisor_id):
            if not summary.needs_attention:
                continue
            for item in summary.items:
                if item.itinerary_id is not None and item.kind in ACTIONABLE_KINDS:
                    attention_itineraries.add(item.itinerary_id)

    next_cursor: str | None = None
    if len(rows) == page_limit and rows:
        last = rows[-1][0]
        last_v = last.title if sort == "title" else getattr(last, sort).isoformat()
        next_cursor = encode_cursor({"v": last_v, "id": str(last.id)})

    return AdvisorItinerariesResponse(
        itineraries=[
            AdvisorItinerarySummary(
                id=itinerary.id,
                title=itinerary.title,
                status=DisplayStatus(bucket),
                created_at=itinerary.created_at,
                updated_at=itinerary.updated_at,
                last_activity_at=itinerary.updated_at,
                client=AdvisorItineraryClient(
                    id=client.id,
                    full_name=client.full_name,
                    email=client.email,
                ),
                needs_attention=itinerary.id in attention_itineraries,
            )
            for itinerary, client, bucket in rows
        ],
        next_cursor=next_cursor,
        total=total,
    )
