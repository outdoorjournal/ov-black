"""Request/response payloads for the advisor-facing clients surface.

Two halves:

- :class:`ClientCreatePayload` — what the advisor POSTs when creating a
  new client + Voodoo Doll. The typed core mirrors the migration columns
  exactly (EmailStr, constrained enums, bounded int lists); the JSONB
  long-tail (``VoodooDollJsonb``) accepts ``dict``/``list`` with shallow
  validation only — the Voodoo Doll schema is intentionally evolvable
  per S03 research §Voodoo Doll schema volatility, so pinning tight
  shapes here would force a migration on every product tweak.
- :class:`ClientCreateResponse` — what the HTTP layer returns on success.

Nothing in this module touches SQLAlchemy; the service layer translates
between the Pydantic payload and the ORM rows.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, conint, conlist

from app.models.client import ContactChannel, GroupType


class VoodooDollTyped(BaseModel):
    """Typed core of the Voodoo Doll — stable signals with a fixed shape."""

    model_config = ConfigDict(extra="forbid")

    contact_preference: ContactChannel
    group_type: GroupType
    children_ages: conlist(conint(ge=0, le=25), max_length=12) = Field(  # type: ignore[valid-type]
        default_factory=list,
    )
    travel_party_notes: str = Field(default="", max_length=2000)
    estimated_net_worth_usd: int | None = Field(default=None, ge=0)


class VoodooDollJsonb(BaseModel):
    """Evolving long-tail — JSONB columns kept shallow on purpose.

    Every field defaults to its migration default so the payload can omit
    whatever the advisor has not filled in yet. Shape-wise, ``dict``/``list``
    is all we enforce here; detailed structure will harden once S04's agent
    starts grounding on these fields.
    """

    model_config = ConfigDict(extra="forbid")

    passions: list[dict[str, Any]] = Field(default_factory=list)
    motivations: dict[str, Any] = Field(default_factory=dict)
    travel_history: list[dict[str, Any]] = Field(default_factory=list)
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    deal_breakers: list[dict[str, Any]] = Field(default_factory=list)
    dream_trip_signals: dict[str, Any] = Field(default_factory=dict)
    osint_notes: dict[str, Any] = Field(default_factory=dict)


class VoodooDollPayload(BaseModel):
    """Full Voodoo Doll — typed core + JSONB long-tail, both present."""

    model_config = ConfigDict(extra="forbid")

    typed: VoodooDollTyped
    jsonb: VoodooDollJsonb = Field(default_factory=VoodooDollJsonb)


class ClientCreatePayload(BaseModel):
    """Payload for ``POST /clients``: a new client + their Voodoo Doll."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    voodoo_doll: VoodooDollPayload


class ClientCreateResponse(BaseModel):
    """Response for ``POST /clients`` on the successful path.

    The action_link from Supabase is deliberately omitted — it is a
    single-use login credential and must not cross the HTTP boundary.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    invite_email: EmailStr
