"""Advisor awareness feed — ``/awareness`` (ADV-14, Wave D).

The read side of the awareness layer: a per-client rollup of "what wants my
attention" (open change requests + unread messages) plus recent activity
(traveler approvals + payments), derived from already-persisted state by
:mod:`app.services.awareness`. Two shapes over one service:

- ``GET /awareness`` — every client of the calling advisor that has *any*
  signal, newest-first. Powers the Command Center roster badges.
- ``GET /awareness/clients/{client_id}`` — one client's feed (empty when
  nothing is pending). Powers the client-detail "what's happened" strip.

Both are :func:`require_advisor` and scoped to ``clients.owner_id`` — a foreign
client id returns the empty feed (no existence leak, D015 posture).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.routers.clients import _advisor_id
from app.services.awareness import (
    AttentionKind,
    ClientAttention,
    load_advisor_attention,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/awareness", tags=["awareness"])


class AttentionItemOut(BaseModel):
    """One signal on one (client, itinerary) — a strip row."""

    model_config = ConfigDict(extra="forbid")

    kind: AttentionKind
    itinerary_id: uuid.UUID | None
    itinerary_title: str | None
    count: int
    at: datetime


class ClientAttentionOut(BaseModel):
    """A client's rolled-up attention — the roster badge + the strip feed."""

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    needs_attention: bool
    attention_count: int
    items: list[AttentionItemOut]
    latest_at: datetime | None


class AwarenessResponse(BaseModel):
    """Envelope for ``GET /awareness`` — clients with a live signal, newest-first."""

    model_config = ConfigDict(extra="forbid")

    clients: list[ClientAttentionOut]


def _to_out(attention: ClientAttention) -> ClientAttentionOut:
    return ClientAttentionOut(
        client_id=attention.client_id,
        needs_attention=attention.needs_attention,
        attention_count=attention.attention_count,
        items=[
            AttentionItemOut(
                kind=item.kind,
                itinerary_id=item.itinerary_id,
                itinerary_title=item.itinerary_title,
                count=item.count,
                at=item.at,
            )
            for item in attention.items
        ],
        latest_at=attention.latest_at,
    )


@router.get(
    "",
    response_model=AwarenessResponse,
    summary="Per-client attention rollup across the calling advisor's roster.",
)
async def get_awareness_endpoint(
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> AwarenessResponse:
    advisor_id = _advisor_id(user)
    summaries = await load_advisor_attention(session, advisor_id=advisor_id)
    return AwarenessResponse(clients=[_to_out(s) for s in summaries])


@router.get(
    "/clients/{client_id}",
    response_model=ClientAttentionOut,
    summary="One client's attention feed (empty when nothing is pending).",
)
async def get_client_awareness_endpoint(
    client_id: uuid.UUID,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ClientAttentionOut:
    advisor_id = _advisor_id(user)
    summaries = await load_advisor_attention(session, advisor_id=advisor_id, client_id=client_id)
    if summaries:
        return _to_out(summaries[0])
    # No signal (or a client this advisor doesn't own) → the empty feed.
    return ClientAttentionOut(
        client_id=client_id,
        needs_attention=False,
        attention_count=0,
        items=[],
        latest_at=None,
    )
