"""Normalized ``InventoryItem`` discriminated union + nested value types.

Every inventory provider (OV, mock, future third-party) returns items in
this shape so callers — search endpoints, agent tools, node-creation
flows — never branch on source. The union is tagged on ``kind`` so
FastAPI emits a clean OpenAPI schema and the generated TS client gets a
proper discriminated union for S07/S09 cards.

M001 only exercises ``experience`` (OV is adventure-trips), but all seven
variants are landed upfront: adding a kind later forces a migration of
the generated client, and the PRD already nails these seven.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Location(BaseModel):
    """Geographic anchor for an inventory item."""

    model_config = {"extra": "ignore"}

    lat: float | None = None
    lng: float | None = None
    label: str | None = None  # e.g. "Lake Como, Italy"


class Price(BaseModel):
    """Price range — providers often return a min/max per-person figure."""

    model_config = {"extra": "ignore"}

    amount_min: float | None = None
    amount_max: float | None = None
    currency: str | None = None  # ISO 4217, e.g. "USD"


class Range(BaseModel):
    """Inclusive numeric range used for duration_days, difficulty, etc."""

    model_config = {"extra": "ignore"}

    min: float | None = None
    max: float | None = None


class EditorialLink(BaseModel):
    """A curated external link — article, guide, trip report."""

    model_config = {"extra": "ignore"}

    url: str
    title: str | None = None


class InventoryItemBase(BaseModel):
    """Fields common to every item variant.

    Concrete variants add a ``kind`` literal (the discriminator) plus
    kind-specific fields. Provider-internal payloads live in ``raw`` and
    must never be relied on by callers — they exist for debugging and
    eventual re-normalization, not for UI rendering.
    """

    model_config = {"extra": "ignore"}

    source: str  # e.g. "ov", "mock"
    source_id: str  # vendor identifier
    title: str
    description: str | None = None
    photos: list[str] = []  # hero image first
    location: Location | None = None
    price: Price | None = None
    editorial_links: list[EditorialLink] = []
    tags: list[str] = []  # e.g. ["hiking", "unesco"]
    # Point-of-interest enrichment surfaced on the card (Google Places et al.).
    # Generic across providers — a POI has a rating, hours, and contact details
    # regardless of who sourced it. Providers that don't carry these leave the
    # defaults; the card-mapping layer turns them into the rendered ``place``
    # block. ``photo_refs`` are opaque provider photo handles (a Places (New)
    # photo is a resource *name*, not a URL) resolved through the keyed photo
    # proxy — never a client-facing image URL on their own.
    rating: float | None = None  # mean star rating, 1–5
    rating_count: int | None = None  # number of ratings behind ``rating``
    opening_hours: list[str] = []  # human weekday-description lines
    website: str | None = None
    phone: str | None = None
    photo_refs: list[str] = []  # provider photo handles, hero first
    raw: dict[str, Any] = {}  # provider-specific pass-through


class ExperienceItem(InventoryItemBase):
    kind: Literal["experience"] = "experience"
    duration_days: Range | None = None
    difficulty: Range | None = None


class DestinationItem(InventoryItemBase):
    kind: Literal["destination"] = "destination"


class HotelItem(InventoryItemBase):
    kind: Literal["hotel"] = "hotel"
    stars: int | None = None


class FlightItem(InventoryItemBase):
    kind: Literal["flight"] = "flight"


class MealItem(InventoryItemBase):
    kind: Literal["meal"] = "meal"


class TransitItem(InventoryItemBase):
    kind: Literal["transit"] = "transit"
    mode: str | None = None  # "train" | "car" | "ferry" | ...


class NoteItem(InventoryItemBase):
    kind: Literal["note"] = "note"


InventoryItem = Annotated[
    ExperienceItem | DestinationItem | HotelItem | FlightItem | MealItem | TransitItem | NoteItem,
    Field(discriminator="kind"),
]
