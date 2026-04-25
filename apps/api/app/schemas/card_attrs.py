"""Per-type card attribute schemas — TravelGraph Phase 2.

Each ``NodeType`` value gets its own Pydantic model capturing the fields
the corresponding card UI consumes (Cards_Style_Guide.md + Itinerary
Planning System / TravelGraph analysis doc §3). Models are united into a
discriminated union keyed on ``kind`` so a heterogeneous metadata blob
parses into the right model with one ``TypeAdapter.validate_python`` call.

Design choices:

- **All fields are optional.** Real itineraries are gathered conversationally
  over many turns; the agent rarely has every field at first contact. The
  schema documents the *shape* the cards expect; presence/absence is up to
  the caller. Tighter validation (e.g. requiring ``iata_from`` on a flight)
  is a job for a later phase, ideally driven by status — a ``confirmed``
  flight without a flight code should fail, but an ``idea`` flight should
  not.
- **No SQLAlchemy here.** This module is pure schema; the service layer
  translates between ``Node.metadata_`` (jsonb) and ``CardAttributes``.
- **Legacy kinds stay supported.** ``transit`` and ``destination`` were
  superseded in Phase 1 by the granular transit modes and ``node_role``
  but existing rows still use them, so the union keeps them.
- **Re-uses NodeType values verbatim.** The discriminator literal must
  match the Postgres enum exactly so a node row can be turned into a
  validated model without remapping.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# ── Helper sub-models ──────────────────────────────────────────────────


class GeoPoint(BaseModel):
    """Lat/lng (+ optional human label) used by every card type that has
    a place. Mirrors the prototype fixture's ``{lat, lng, label?}``.
    """

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    label: str | None = None


class CardSnapshot(BaseModel):
    """Lightweight glance preview embedded by hotel/experience/meal cards
    so the timeline can render the chip strip without re-fetching the full
    row. Mirrors the prototype's ``snapshot`` field.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    cover_image: str | None = None
    price: str | None = None
    duration_days: int | None = None
    difficulty: str | None = None
    location: str | None = None
    activities: list[str] = Field(default_factory=list)


class TimeOfDayWindow(BaseModel):
    """24-hour start/end pair for "best window" overlays (experience cards)."""

    model_config = ConfigDict(extra="forbid")

    start_hour: int = Field(ge=0, le=24)
    end_hour: int = Field(ge=0, le=24)


# ── Subway / train sub-models ─────────────────────────────────────────


class SubwayLine(BaseModel):
    """One leg of a subway journey, colored by agency line color."""

    model_config = ConfigDict(extra="forbid")

    name: str
    agency_color: str | None = None  # hex, e.g. "#f39700" (Tokyo Metro Ginza)


class SubwayTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: str
    line_color: str | None = None


class SignageGloss(BaseModel):
    """Native script + romanization + traveler-language gloss tile.

    Only attached when the local script differs from the traveler's
    language; the renderer collapses to a single line otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    native: str
    romanization: str | None = None
    traveler_lang: str | None = None


class TrainStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station: str
    arrives_at: datetime | None = None
    departs_at: datetime | None = None


class SceneryCallout(BaseModel):
    """"Mt. Fuji, north window, from 12:55" — the train card's signature
    detail. Specific minute + side, not a vague "scenic route" tag.
    """

    model_config = ConfigDict(extra="forbid")

    minute_offset: int | None = None  # minutes from depart_at
    side: Literal["left", "right", "front", "rear"] | None = None
    what: str


# ── Drive sub-models ──────────────────────────────────────────────────


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    make: str | None = None
    capacity: int | None = None  # passenger seats
    plate: str | None = None
    plate_native_script: str | None = None  # e.g. 品川 300 あ 12-34


class Driver(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    photo_url: str | None = None
    languages: list[str] = Field(default_factory=list)
    contact_link: str | None = None


# ── Hotel sub-models ──────────────────────────────────────────────────


class WalkingDistance(BaseModel):
    """"From your door" walking time to one upcoming itinerary node.

    Hotel card's signature detail (Cards_Style_Guide.md §hotel) — connects
    the lodging to the day around it.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    minutes: int
    mode: str | None = None  # "indoor", "covered", default = walk
    target_node_id: uuid.UUID | None = None


# ── Meal sub-models ───────────────────────────────────────────────────


class EtiquetteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    body: str


class Phrase(BaseModel):
    """Pre-meal / signage phrase. Same shape as SignageGloss but kept as
    a distinct type so the renderer can pick the right component.
    """

    model_config = ConfigDict(extra="forbid")

    native: str
    romanization: str | None = None
    gloss: str | None = None


# ── Common base for every card model ──────────────────────────────────


class _CardBase(BaseModel):
    """Fields shared across every card kind.

    ``kind`` is set on each subclass to the matching ``NodeType`` value
    so the discriminated union below can route a raw dict to the right
    class. Subclasses must NOT redeclare this field.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    body: str | None = None
    ambient_image: str | None = None
    time_of_day: (
        Literal["morning", "lunch", "afternoon", "evening", "night"] | None
    ) = None
    location: GeoPoint | None = None
    duration_minutes: int | None = Field(default=None, ge=0)


# ── Per-type card models ──────────────────────────────────────────────


class FlightCardAttrs(_CardBase):
    kind: Literal["flight"] = "flight"
    iata_from: str | None = None
    iata_to: str | None = None
    flight_code: str | None = None
    cabin: str | None = None
    seat: str | None = None
    terminal: str | None = None
    gate: str | None = None
    aircraft: str | None = None
    miles: int | None = None
    tz_delta_hours: int | None = None
    scenic_side: Literal["left", "right"] | None = None
    lounge_proximity: str | None = None
    jet_lag_protocol: str | None = None
    wifi: str | None = None
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    snapshot: CardSnapshot | None = None


class SubwayCardAttrs(_CardBase):
    kind: Literal["subway"] = "subway"
    from_station: str | None = None
    to_station: str | None = None
    lines: list[SubwayLine] = Field(default_factory=list)
    transfers: list[SubwayTransfer] = Field(default_factory=list)
    fare_or_pass_note: str | None = None
    signage_gloss: list[SignageGloss] = Field(default_factory=list)
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None
    mode: str | None = None  # short summary string ("Tokyo Metro · IC card")


class TrainCardAttrs(_CardBase):
    kind: Literal["train"] = "train"
    from_station: str | None = None
    to_station: str | None = None
    train_name: str | None = None
    train_number: str | None = None
    platform: str | None = None
    car: str | None = None
    seat: str | None = None
    pass_eligibility: str | None = None
    food_on_board: str | None = None
    stops: list[TrainStop] = Field(default_factory=list)
    scenery_callouts: list[SceneryCallout] = Field(default_factory=list)
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    mode: str | None = None  # "JR Pass · reserved seats"


class DriveCardAttrs(_CardBase):
    kind: Literal["drive"] = "drive"
    eta_minutes: int | None = None
    vehicle: Vehicle | None = None
    driver: Driver | None = None
    bag_capacity: int | None = None
    prior_trip_continuity: bool | None = None
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None
    # Encoded polyline string. PostGIS LineString lives on Node.route,
    # already created in Phase 1; this field is the on-the-wire summary.
    route_polyline: str | None = None


class WalkCardAttrs(_CardBase):
    kind: Literal["walk"] = "walk"
    distance_m: int | None = Field(default=None, ge=0)
    surface_notes: list[str] = Field(default_factory=list)
    pois_along: list[GeoPoint] = Field(default_factory=list)
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None


class BoatCardAttrs(_CardBase):
    kind: Literal["boat"] = "boat"
    dock_from: str | None = None
    dock_to: str | None = None
    motion_sickness_rating: (
        Literal["none", "mild", "moderate", "rough"] | None
    ) = None
    bring_with: list[str] = Field(default_factory=list)
    schedule_frequency: str | None = None
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None


class TransitCardAttrs(_CardBase):
    """Legacy collapsed transit type — superseded in Phase 1 by the granular
    subway/train/drive/walk/boat kinds. Kept for back-compat with rows
    that haven't been remigrated.
    """

    kind: Literal["transit"] = "transit"
    mode: str | None = None
    from_location: GeoPoint | None = None
    to_location: GeoPoint | None = None


class HotelCardAttrs(_CardBase):
    kind: Literal["hotel"] = "hotel"
    name: str | None = None
    room_type: str | None = None
    nights: int | None = None
    check_in: datetime | None = None
    check_out: datetime | None = None
    confirmation_number: str | None = None
    bedding: str | None = None
    in_room_amenities: list[str] = Field(default_factory=list)
    walking_to: list[WalkingDistance] = Field(default_factory=list)
    profile_prefs_honored: list[str] = Field(default_factory=list)
    neighborhood_blurb: str | None = None
    snapshot: CardSnapshot | None = None
    # Renderer hint: lodging spans the night, draw the day-bar with a
    # softer night band. Distinct from ``time_of_day`` (which marks meals
    # and experiences inside the day arc).
    night_bar: bool | None = None


class ExperienceCardAttrs(_CardBase):
    kind: Literal["experience"] = "experience"
    category: str | None = None
    energy_required: int | None = Field(default=None, ge=1, le=5)
    energy_after: (
        Literal["depleting", "neutral", "restorative"] | None
    ) = None
    difficulty: str | None = None
    best_window: TimeOfDayWindow | None = None
    gear_list: list[str] = Field(default_factory=list)
    weather_contingency: str | None = None
    allergens: list[str] = Field(default_factory=list)
    age_min: int | None = None
    language_support: str | None = None
    group_size: str | None = None
    snapshot: CardSnapshot | None = None


class MealCardAttrs(_CardBase):
    kind: Literal["meal"] = "meal"
    cuisine_class: str | None = None
    seating_at: datetime | None = None
    dress_code: str | None = None
    dietary_flags: list[str] = Field(default_factory=list)
    etiquette: list[EtiquetteItem] = Field(default_factory=list)
    pre_meal_phrases: list[Phrase] = Field(default_factory=list)
    reservation_number: str | None = None
    cancellation_policy: str | None = None
    price: str | None = None
    snapshot: CardSnapshot | None = None


class FreeTimeCardAttrs(_CardBase):
    kind: Literal["free_time"] = "free_time"
    weather: str | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    energy_advice: str | None = None
    suggestion_grid: list[str] = Field(default_factory=list)


class WaitingCardAttrs(_CardBase):
    kind: Literal["waiting"] = "waiting"
    whats_next_node_id: uuid.UUID | None = None
    lounge_info: str | None = None
    use_this_time_to: list[str] = Field(default_factory=list)
    facilities: list[str] = Field(default_factory=list)
    soft_progress_bar: bool | None = None  # only show if duration >= 30 min


class NoteCardAttrs(_CardBase):
    """Note attributes. The dual-mode anchoring (attached vs. free-standing)
    lives on the Node row itself (``attached_to_node_id`` / ``starts_at``)
    not in attributes — see Phase 1 / migration 0014.
    """

    kind: Literal["note"] = "note"
    author_name: str | None = None
    author_role: str | None = None
    tags: list[str] = Field(default_factory=list)
    visibility: Literal["private", "team", "shared"] | None = None


class DestinationCardAttrs(_CardBase):
    """Legacy ``destination`` node_type. Phase 1 introduced ``node_role``
    as the structural axis; new code should set ``role='destination'``
    on an ordinary node rather than using this kind.
    """

    kind: Literal["destination"] = "destination"
    region_map_url: str | None = None
    language_hint: str | None = None
    climate: str | None = None


# ── Discriminated union ───────────────────────────────────────────────


CardAttributes = Annotated[
    FlightCardAttrs
    | SubwayCardAttrs
    | TrainCardAttrs
    | DriveCardAttrs
    | WalkCardAttrs
    | BoatCardAttrs
    | TransitCardAttrs
    | HotelCardAttrs
    | ExperienceCardAttrs
    | MealCardAttrs
    | FreeTimeCardAttrs
    | WaitingCardAttrs
    | NoteCardAttrs
    | DestinationCardAttrs,
    Field(discriminator="kind"),
]

_CARD_ADAPTER: TypeAdapter[CardAttributes] = TypeAdapter(CardAttributes)


def parse_card_attrs(node_type: str, raw: dict | None) -> CardAttributes:
    """Validate ``raw`` metadata against the model that matches ``node_type``.

    ``kind`` is injected from ``node_type`` so callers don't have to set
    it; an explicit ``kind`` in ``raw`` that disagrees with ``node_type``
    raises a ValidationError because Pydantic enforces the discriminator
    match.

    A ``raw`` of ``None`` or ``{}`` is fine — every field is optional.
    """
    payload = {**(raw or {}), "kind": node_type}
    return _CARD_ADAPTER.validate_python(payload)


__all__ = [
    "BoatCardAttrs",
    "CardAttributes",
    "CardSnapshot",
    "DestinationCardAttrs",
    "DriveCardAttrs",
    "Driver",
    "EtiquetteItem",
    "ExperienceCardAttrs",
    "FlightCardAttrs",
    "FreeTimeCardAttrs",
    "GeoPoint",
    "HotelCardAttrs",
    "MealCardAttrs",
    "NoteCardAttrs",
    "Phrase",
    "SceneryCallout",
    "SignageGloss",
    "SubwayCardAttrs",
    "SubwayLine",
    "SubwayTransfer",
    "TimeOfDayWindow",
    "TrainCardAttrs",
    "TrainStop",
    "TransitCardAttrs",
    "Vehicle",
    "WaitingCardAttrs",
    "WalkCardAttrs",
    "WalkingDistance",
    "parse_card_attrs",
]
