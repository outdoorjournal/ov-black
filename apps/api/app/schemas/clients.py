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
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.contacts import ClientContactCreate, ClientContactDetail
from app.schemas.dossier import DossierDetail, DossierPayload
from app.schemas.facts import (
    DossierFactCreate,
    DossierFactDetail,
    OsintFactCreate,
    OsintFactDetail,
    ProfileFactCreate,
    ProfileFactDetail,
)

# Shared validated field types for the three traveler-logistics columns (0048).
# ``favorite_airport`` is an IATA code, ``preferred_currency`` an ISO 4217 code;
# both are stored upper-case and pinned to 3 letters (matching the DB CHECKs).
IataAirport = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]
Iso4217Currency = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]
# ISO 3166-1 alpha-2 country code (0051), stored upper-cased (matches the DB CHECK).
CountryCodeAlpha2 = Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")]


class ClientCreatePayload(BaseModel):
    """Payload for ``POST /clients``: a new client + their Dossier.

    Three optional initial fact seeds (one per tier) are written in the
    same atomic transaction as the client + dossier rows so onboarding
    stays one round-trip even when the advisor records knowledge across
    all three disclosure tiers up front.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    # Optional traveler-logistics seeds (0048) — the onboarding form may know
    # the home airport / preferred currency / address up front.
    address: str | None = Field(default=None, max_length=2000)
    favorite_airport: IataAirport | None = None
    preferred_currency: Iso4217Currency | None = None
    dossier: DossierPayload
    dossier_facts: list[DossierFactCreate] = Field(default_factory=list)
    profile_facts: list[ProfileFactCreate] = Field(default_factory=list)
    osint_facts: list[OsintFactCreate] = Field(default_factory=list)
    contacts: list[ClientContactCreate] = Field(default_factory=list)
    # When true (default, the atomic path) the create also mints the Supabase
    # auth row and emails a welcome sign-in link. When false the advisor is
    # standing the client up silently to build for them first — no auth row, no
    # email — and invites later via ``POST /clients/{id}/resend-welcome``.
    notify: bool = True


class ClientCreateResponse(BaseModel):
    """Response for ``POST /clients`` on the successful path.

    The action_link from Supabase is deliberately omitted — it is a
    single-use login credential and must not cross the HTTP boundary.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    email: EmailStr


class ClientUpdatePayload(BaseModel):
    """Partial update for the traveler-logistics fields via ``PATCH /clients/{id}``.

    Every field is optional; only the keys actually present in the request
    body are applied (the route reads ``model_fields_set``), so passing an
    explicit ``null`` clears a field while omitting it leaves it untouched.
    Airport + currency codes are stored upper-cased.
    """

    model_config = ConfigDict(extra="forbid")

    address: str | None = Field(default=None, max_length=2000)
    favorite_airport: IataAirport | None = None
    preferred_currency: Iso4217Currency | None = None
    # Structured billing-address parts (0051). `country_code` is stored upper-cased.
    city: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=32)
    country_code: CountryCodeAlpha2 | None = None


# Where the client sits on the invite → sign-in path. Derived server-side from
# ``clients.invited_at`` + ``clients.auth_user_id``:
#   ``uninvited`` — created silently, never notified (invited_at IS NULL);
#   ``pending``   — welcome link issued, awaiting first login;
#   ``active``    — signed in (auth_user_id backfilled).
AccessStatus = Literal["uninvited", "pending", "active"]


class ClientSummary(BaseModel):
    """Row shape for ``GET /clients``."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr
    has_dossier: bool
    access_status: AccessStatus
    # When the welcome link was first issued (None while ``uninvited``).
    invited_at: datetime | None
    # When the client first signed in (None until ``active``).
    accepted_at: datetime | None
    created_at: datetime


class ClientsPage(BaseModel):
    """Envelope for ``GET /clients`` (Wave F — breaking: was a bare list).

    ``total`` counts every row matching the q/status filters (not the page),
    so the roster chrome can say "42 clients" without a second call.
    """

    model_config = ConfigDict(extra="forbid")

    clients: list[ClientSummary]
    next_cursor: str | None
    total: int


class ClientDetail(BaseModel):
    """Full client + dossier + per-tier fact lists for ``GET /clients/{id}``.

    Fact lists default to active rows only (``redacted_at IS NULL``);
    advisors who want to see redacted history can pass
    ``?include_redacted=1`` on the request.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    full_name: str
    email: EmailStr
    access_status: AccessStatus
    invited_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Traveler logistics (0048). None = not yet recorded.
    address: str | None = None
    favorite_airport: str | None = None
    preferred_currency: str | None = None
    # Structured billing-address parts (0051). None = not yet recorded.
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    dossier: DossierDetail | None
    dossier_facts: list[DossierFactDetail] = Field(default_factory=list)
    profile_facts: list[ProfileFactDetail] = Field(default_factory=list)
    osint_facts: list[OsintFactDetail] = Field(default_factory=list)
    contacts: list[ClientContactDetail] = Field(default_factory=list)
