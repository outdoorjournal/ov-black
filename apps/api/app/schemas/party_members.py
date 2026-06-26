"""Pydantic shapes for party members (M003/V1).

A party member is the durable, household-scoped traveler identity (0019) —
reused across every itinerary a client takes. Three actors author them (advisor,
traveler self-service, agent), so the create/update bodies never carry an actor:
it is fixed server-side per endpoint, exactly like fact ``source_kind``.

Input is validated with typed sub-models (``LoyaltyProgram`` / ``EmergencyContact``);
the JSONB fields are returned as raw passthrough on the detail shape so a member
authored with extra keys (e.g. by a future agent) still serializes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.party import PartyMemberActor

# ── nested value objects ─────────────────────────────────────────────────


class LoyaltyProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str = Field(min_length=1, max_length=120)
    number: str = Field(min_length=1, max_length=120)


class EmergencyContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    relationship: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=60)


# ── write shapes (actor fixed server-side) ───────────────────────────────


class PartyMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=120)
    dietary: str | None = Field(default=None, max_length=2000)
    medical: str | None = Field(default=None, max_length=2000)
    mobility: str | None = Field(default=None, max_length=2000)
    loyalty_programs: list[LoyaltyProgram] = Field(default_factory=list)
    emergency_contact: EmergencyContact | None = None
    relationship_to_primary: str | None = Field(default=None, max_length=120)
    is_primary: bool = False
    notes: str | None = Field(default=None, max_length=4000)


class PartyMemberUpdate(BaseModel):
    """All-optional patch; only fields explicitly set are applied."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=120)
    dietary: str | None = Field(default=None, max_length=2000)
    medical: str | None = Field(default=None, max_length=2000)
    mobility: str | None = Field(default=None, max_length=2000)
    loyalty_programs: list[LoyaltyProgram] | None = None
    emergency_contact: EmergencyContact | None = None
    relationship_to_primary: str | None = Field(default=None, max_length=120)
    is_primary: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


# ── read shapes ──────────────────────────────────────────────────────────


class PartyMemberDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    full_name: str
    date_of_birth: date | None
    nationality: str | None
    dietary: str | None
    medical: str | None
    mobility: str | None
    loyalty_programs: list[dict[str, Any]]
    emergency_contact: dict[str, Any]
    relationship_to_primary: str | None
    is_primary: bool
    notes: str | None
    created_by_actor: PartyMemberActor
    updated_by_actor: PartyMemberActor
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PartyMemberListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[PartyMemberDetail]


# ── per-trip participation (attach a member to an itinerary's party) ──────


class AttachPartyMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_member_id: uuid.UUID


class ItineraryPartyEntry(BaseModel):
    """One traveler on an itinerary's party, with its durable member resolved."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: uuid.UUID
    party_id: uuid.UUID
    name: str
    party_member_id: uuid.UUID | None
    member: PartyMemberDetail | None


class ItineraryPartyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itinerary_id: uuid.UUID
    members: list[ItineraryPartyEntry]
