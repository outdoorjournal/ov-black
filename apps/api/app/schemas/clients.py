"""Request/response payloads for the advisor-facing clients surface.

- :class:`ClientCreatePayload` — what the advisor POSTs when creating a
  new client + Dossier. The typed core mirrors the migration columns
  exactly. Optional ``dossier_facts`` lets the onboarding form seed an
  initial set of long-tail facts atomically with the client + dossier.
- :class:`ClientCreateResponse` — what the HTTP layer returns on success.
- :class:`ClientSummary` / :class:`ClientDetail` — read-through shapes for
  ``GET /clients`` (list) and ``GET /clients/{id}`` (full join, including
  active facts in all three tiers).

Nothing in this module touches SQLAlchemy; the service layer translates
between the Pydantic payload and the ORM rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.dossier import DossierDetail, DossierPayload
from app.schemas.facts import (
    DossierFactCreate,
    DossierFactDetail,
    OsintFactDetail,
    ProfileFactDetail,
)


class ClientCreatePayload(BaseModel):
    """Payload for ``POST /clients``: a new client + their Dossier.

    ``dossier_facts`` is an optional initial seed of long-tail facts
    (passions, motivations, …) — written in the same atomic transaction
    as the client + dossier rows so onboarding stays one round-trip.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    dossier: DossierPayload
    dossier_facts: list[DossierFactCreate] = Field(default_factory=list)


class ClientCreateResponse(BaseModel):
    """Response for ``POST /clients`` on the successful path.

    The action_link from Supabase is deliberately omitted — it is a
    single-use login credential and must not cross the HTTP boundary.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    invite_email: EmailStr


InviteStatus = Literal["pending", "consumed", "cancelled", "none"]
InviteEventStatus = Literal["active", "consumed", "cancelled", "superseded"]


class InviteEvent(BaseModel):
    """A single invite send — one row in the invite history for a client.

    The raw ``code`` is deliberately omitted. Codes are bearer credentials;
    the advisor UI needs timestamps + lifecycle state to render the history,
    not the codes themselves.
    """

    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    consumed_at: datetime | None
    cancelled_at: datetime | None
    superseded_at: datetime | None
    status: InviteEventStatus


class ClientSummary(BaseModel):
    """Row shape for ``GET /clients``."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr
    has_dossier: bool
    invite_status: InviteStatus
    created_at: datetime


class ClientDetail(BaseModel):
    """Full client + dossier + per-tier fact lists for ``GET /clients/{id}``.

    ``invite_history`` lists every send for this client, newest first.
    ``invite_status`` is the derived current state and duplicates what
    the top of ``invite_history`` implies — consumers can read either.

    Fact lists default to active rows only (``redacted_at IS NULL``);
    advisors who want to see redacted history can pass
    ``?include_redacted=1`` on the request.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr
    invite_status: InviteStatus
    invite_history: list[InviteEvent]
    created_at: datetime
    updated_at: datetime
    dossier: DossierDetail | None
    dossier_facts: list[DossierFactDetail] = Field(default_factory=list)
    profile_facts: list[ProfileFactDetail] = Field(default_factory=list)
    osint_facts: list[OsintFactDetail] = Field(default_factory=list)
