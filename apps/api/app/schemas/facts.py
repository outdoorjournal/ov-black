"""Pydantic shapes for the three per-fact tiers (Dossier / Profile / OSINT).

Each tier shares a structural template (text + source_kind + source_ref +
observed_at + redaction fields) but pins its kind enum and source_kind
domain to a tier-specific subset enforced DB-side via CHECK constraints.

Two extra shapes are agent-only:

- :class:`AgentContext` — the response of ``GET /agent/context`` (the
  backend-only endpoint the agent calls with its per-session token to
  receive all three tiers in one round-trip).
- :class:`AgentRecordProfileFactRequest` /
  :class:`AgentRecordDossierInferenceRequest` — bodies the agent posts
  when the traveler tells it something or when it makes an internal
  inference. ``source_kind`` is fixed server-side per endpoint; the
  agent cannot choose.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.dossier_fact import DossierFactKind, FactSourceKind
from app.models.osint_fact import OsintFactKind
from app.models.profile_fact import ProfileFactKind
from app.schemas.dossier import DossierDetail
from app.schemas.party_members import PartyMemberDetail

# ── Dossier facts ────────────────────────────────────────────────────────


class DossierFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DossierFactKind
    text: str = Field(min_length=1, max_length=4000)
    source_kind: Literal[FactSourceKind.advisor, FactSourceKind.agent_inferred] = (
        FactSourceKind.advisor
    )
    source_ref: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None


class DossierFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DossierFactKind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4000)


class DossierFactDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: DossierFactKind
    text: str
    source_kind: FactSourceKind
    source_ref: dict[str, Any]
    observed_at: datetime
    recorded_by: uuid.UUID
    redacted_at: datetime | None
    redacted_by: uuid.UUID | None
    redacted_reason: str | None
    created_at: datetime
    updated_at: datetime


# ── Profile facts ────────────────────────────────────────────────────────


class ProfileFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProfileFactKind
    text: str = Field(min_length=1, max_length=4000)
    source_kind: Literal[FactSourceKind.advisor, FactSourceKind.traveler_told] = (
        FactSourceKind.advisor
    )
    source_ref: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None


class ProfileFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProfileFactKind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4000)


class ProfileFactDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: ProfileFactKind
    text: str
    source_kind: FactSourceKind
    source_ref: dict[str, Any]
    observed_at: datetime
    recorded_by: uuid.UUID
    redacted_at: datetime | None
    redacted_by: uuid.UUID | None
    redacted_reason: str | None
    created_at: datetime
    updated_at: datetime


# ── OSINT facts ──────────────────────────────────────────────────────────


class OsintFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: OsintFactKind
    text: str = Field(min_length=1, max_length=4000)
    source_kind: Literal[FactSourceKind.advisor, FactSourceKind.scraper] = FactSourceKind.advisor
    source_ref: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime | None = None


class OsintFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: OsintFactKind | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4000)


class OsintFactDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: OsintFactKind
    text: str
    source_kind: FactSourceKind
    source_ref: dict[str, Any]
    observed_at: datetime
    recorded_by: uuid.UUID
    redacted_at: datetime | None
    redacted_by: uuid.UUID | None
    redacted_reason: str | None
    created_at: datetime
    updated_at: datetime


# ── Common ───────────────────────────────────────────────────────────────


class RedactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


# ── Agent-only shapes ────────────────────────────────────────────────────


class AgentContext(BaseModel):
    """Single-payload response of ``GET /agent/context``.

    Returned only to the agent (authenticated by the per-session agent
    token) — never to the traveler's browser.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: uuid.UUID
    client_full_name: str
    # Traveler logistics (0048), client-level and non-private: the home airport
    # (IATA — the DEFAULT departure origin for flights, so the agent never has to
    # guess one), the home base address, and the currency to quote prices in. Any
    # may be None when not yet on file — the agent should ask rather than assume.
    home_airport: str | None = None
    home_address: str | None = None
    preferred_currency: str | None = None
    # The pinned itinerary's first-class brief + timing (0033), pre-rendered for
    # the prompt: the goal + when the traveler set at intake. Non-private — the
    # agent grounds suggestions in it and may reference it naturally. None when
    # the session has no pinned itinerary or no brief has been set yet.
    trip_brief: str | None = None
    # The pinned itinerary's live plan state (AGT-2), pre-rendered by
    # app.services.graph_digest: lifecycle status, node counts, totals,
    # uninvoiced remainder. Same block the per-turn system prompt carries —
    # None when the session has no pinned itinerary.
    graph_digest: str | None = None
    dossier: DossierDetail | None
    dossier_facts: list[DossierFactDetail]
    profile_facts: list[ProfileFactDetail]
    osint_facts: list[OsintFactDetail]
    # The durable household roster (0019). SHARED knowledge — unlike Dossier /
    # OSINT, the agent MAY reference and confirm these with the traveler.
    party_members: list[PartyMemberDetail]
    # Fork-awareness (G3). When the session is pinned to a fork, ``is_alternative``
    # is true, ``baseline_title`` names the agreed plan it diverges from, and
    # ``reconcile_requested`` reflects a pending merge ask. The agent uses these to
    # talk about "an alternative version" and whether staff have been asked to merge.
    is_alternative: bool = False
    baseline_title: str | None = None
    reconcile_requested: bool = False


class AgentRecordProfileFactRequest(BaseModel):
    """Body for ``POST /agent/profile/facts`` (agent-only).

    The endpoint always stamps ``source_kind=traveler_told`` regardless of
    what the agent might supply — so the field is not part of the request
    shape. ``source_turn_id`` is optional context the agent can attach so
    the command center can link the fact back to the originating turn.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ProfileFactKind
    text: str = Field(min_length=1, max_length=4000)
    source_turn_id: uuid.UUID | None = None


class AgentRecordDossierInferenceRequest(BaseModel):
    """Body for ``POST /agent/dossier/facts`` (agent-only).

    The endpoint always stamps ``source_kind=agent_inferred``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: DossierFactKind
    text: str = Field(min_length=1, max_length=4000)
    source_turn_id: uuid.UUID | None = None


# Validated field types for the traveler-logistics write (0048). Defined here
# (not imported from schemas.clients) because clients.py imports from this
# module — pulling the other way would be a circular import. The patterns match
# the DB CHECKs: IATA / ISO 4217 are three letters, stored upper-cased.
_AgentIataAirport = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]
_AgentIso4217Currency = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]


class AgentRecordTravelLogisticsRequest(BaseModel):
    """Body for ``PATCH /agent/logistics`` (agent-only).

    Lets the agent persist client-level logistics it learned in conversation —
    the home airport (default flight origin), home address, and preferred
    currency. All fields optional; pass only what was learned this turn.

    Overwrite discipline: the endpoint fills a field only when it is currently
    unset (or the new value matches). An existing, *different* value is left
    untouched and reported back as a conflict unless ``confirm_overwrite`` is
    true — so the agent confirms a correction with the traveler before clobbering
    something staff or the traveler set earlier.
    """

    model_config = ConfigDict(extra="forbid")

    home_airport: _AgentIataAirport | None = None
    home_address: str | None = Field(default=None, max_length=2000)
    preferred_currency: _AgentIso4217Currency | None = None
    confirm_overwrite: bool = False


class AgentLogisticsConflict(BaseModel):
    """One field the write declined to overwrite without confirmation."""

    model_config = ConfigDict(extra="forbid")

    field: Literal["home_airport", "home_address", "preferred_currency"]
    existing: str
    proposed: str


class AgentTravelLogisticsResult(BaseModel):
    """Response of ``PATCH /agent/logistics``.

    Echoes the logistics after the write and lists any fields skipped because
    they already held a different value (and ``confirm_overwrite`` was false),
    each with the ``existing`` value so the agent can ask before overwriting.
    """

    model_config = ConfigDict(extra="forbid")

    home_airport: str | None = None
    home_address: str | None = None
    preferred_currency: str | None = None
    skipped: list[AgentLogisticsConflict] = Field(default_factory=list)
