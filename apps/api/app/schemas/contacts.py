"""Pydantic shapes for per-client contact methods (phone / messenger / social)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.client_contact import ContactKind


class ClientContactCreate(BaseModel):
    """POST body for creating a contact row.

    Used both as a top-level create payload and as an embedded element of
    :class:`app.schemas.clients.ClientCreatePayload` when seeding contacts
    atomically at client-creation time.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ContactKind
    value: str = Field(min_length=1, max_length=256)
    label: str = Field(default="", max_length=64)


class ClientContactUpdate(BaseModel):
    """PATCH body — every field is optional; omitted fields stay unchanged."""

    model_config = ConfigDict(extra="forbid")

    kind: ContactKind | None = None
    value: str | None = Field(default=None, min_length=1, max_length=256)
    label: str | None = Field(default=None, max_length=64)


class ClientContactDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: ContactKind
    value: str
    label: str
    created_at: datetime
    updated_at: datetime
