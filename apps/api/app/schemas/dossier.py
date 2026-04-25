"""Pydantic shapes for the Dossier typed core.

Long-tail dossier facts (passions, motivations, …) live in
``app.schemas.facts.DossierFactDetail`` — this module owns only the
small structured-signal row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, conint, conlist

from app.models.client import ContactChannel, GroupType


class DossierTyped(BaseModel):
    """Typed core of the Dossier — stable structured signals."""

    model_config = ConfigDict(extra="forbid")

    contact_preference: ContactChannel
    group_type: GroupType
    children_ages: conlist(conint(ge=0, le=25), max_length=12) = Field(  # type: ignore[valid-type]
        default_factory=list,
    )
    travel_party_notes: str = Field(default="", max_length=2000)
    estimated_net_worth_usd: int | None = Field(default=None, ge=0)


class DossierPayload(BaseModel):
    """Wrapper kept for backward-compat parity with the prior payload shape."""

    model_config = ConfigDict(extra="forbid")

    typed: DossierTyped


class DossierDetail(BaseModel):
    """Full Dossier typed-core read-through shape."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    contact_preference: ContactChannel
    group_type: GroupType
    children_ages: list[int]
    travel_party_notes: str
    estimated_net_worth_usd: int | None
    created_at: datetime
    updated_at: datetime
