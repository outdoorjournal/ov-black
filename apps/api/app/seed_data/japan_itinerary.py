"""Real-trip Japan fixture for TravelGraph tests.

Mirrors a curated subset of the production prototype fixture at
``apps/web/app/prototype/itinerary-graph-vertical/_fixtures/japan.ts``
(15-day Tokyo → Kyoto → Hiroshima → Osaka → Mt Fuji → Tokyo trip from
2024-06-20 → 2024-07-04). The web fixture is the authoring source of
truth; this Python copy stays the same shape so a future round-trip
test can assert byte-for-byte equivalence after the API serializes
through the new card-attrs schema.

Choices:

- We use the granular Phase-1 ``NodeType`` values where the trip data
  clearly indicates them — Shinkansen → ``train``, Tokyo Metro / Keikyu
  Airport Line / IC card local rails → ``subway``, JR airport
  approach where the mode is explicitly "JR" → ``train``. The JS
  fixture's collapsed ``transit`` is preserved for ambiguous legs.
- ``starts_at`` is built as a ``[start, start+duration_minutes)`` range
  so it round-trips the Phase-1 ``tstzrange`` column without losing the
  duration the renderer needs.
- Every item is described with a Pydantic ``CardAttributes`` model so
  the fixture itself fails to load if a schema constraint is violated
  — the file is its own validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.card_attrs import (
    CardAttributes,
    CardSnapshot,
    ExperienceCardAttrs,
    FlightCardAttrs,
    GeoPoint,
    HotelCardAttrs,
    MealCardAttrs,
    NoteCardAttrs,
    SceneryCallout,
    SubwayCardAttrs,
    TrainCardAttrs,
)

# Tokyo wall-clock to UTC. The trip is in JST (+09:00) and the JS fixture
# emits naive timestamps; we tag them explicitly so DB writes round-trip
# correctly through tstzrange.
JST = timezone(timedelta(hours=9))


def _at(date_iso: str, hhmm: str) -> datetime:
    """Compose a tz-aware datetime in JST. Mirrors ``isoTokyo`` from the
    JS fixture's builders.ts.
    """
    h, m = (int(part) for part in hhmm.split(":", 1))
    y, mo, d = (int(part) for part in date_iso.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=JST)


@dataclass(frozen=True)
class FixtureItem:
    """One node in the Japan fixture. ``id_hint`` mirrors the JS fixture
    so cross-file diff is trivial. ``attrs`` is the per-type Pydantic
    model — instantiating it at import time validates the row.
    """

    id_hint: str
    title: str
    starts_at: datetime
    duration_minutes: int
    attrs: CardAttributes


@dataclass(frozen=True)
class FixtureDay:
    date: str
    weather_emoji: str | None
    items: list[FixtureItem] = field(default_factory=list)


# ── Day 01 — arrival ──────────────────────────────────────────────────

HND = GeoPoint(lat=35.5494, lng=139.7798, label="Haneda Airport")
LAX = GeoPoint(lat=33.9416, lng=-118.4085, label="LAX")
SHIN_NAKANO = GeoPoint(lat=35.6930, lng=139.6662, label="Shin-Nakano")

DAY_01 = FixtureDay(
    date="2024-06-20",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day01-arrival",
            title="Arrive Haneda — Delta DL275",
            starts_at=_at("2024-06-20", "16:10"),
            duration_minutes=30,
            attrs=FlightCardAttrs(
                iata_from="LAX",
                iata_to="HND",
                flight_code="DL275",
                from_location=LAX,
                to_location=HND,
                location=HND,
                ambient_image="/japan/day01_passport_stamp_example.jpg",
                description=(
                    "Use Visit Japan Web, then go through a staffed counter "
                    "so you get the Temporary Visitor entry stamp needed "
                    "for the JR Pass."
                ),
                tz_delta_hours=16,  # LAX (-7 PDT) → JST (+9)
                arrive_at=_at("2024-06-20", "16:10"),
            ),
        ),
        FixtureItem(
            id_hint="day01-assistant",
            title="Meet airport assistant at arrivals",
            starts_at=_at("2024-06-20", "16:40"),
            duration_minutes=20,
            attrs=NoteCardAttrs(
                body=(
                    "Mr. Takebayashi Kei · 080-3094-0463. Shows you the IC "
                    "card, validates the JR Pass, escorts you to the apartment."
                ),
                author_role="advisor",
                visibility="shared",
            ),
        ),
        FixtureItem(
            id_hint="day01-train",
            title="Keikyu Airport Line Express → Shin-Nakano",
            starts_at=_at("2024-06-20", "17:00"),
            duration_minutes=79,
            attrs=SubwayCardAttrs(
                from_station="Haneda Airport Terminal 3",
                to_station="Shin-Nakano",
                from_location=HND,
                to_location=SHIN_NAKANO,
                location=SHIN_NAKANO,
                mode="Keikyu Airport Line Express · IC card",
                fare_or_pass_note="IC card · JR Pass not yet valid",
            ),
        ),
        FixtureItem(
            id_hint="day01-checkin",
            title="Apartment self-check-in",
            starts_at=_at("2024-06-20", "18:30"),
            duration_minutes=30,
            attrs=NoteCardAttrs(
                body=("Assistant helps with self-check-in, then service ends. Dinner excluded."),
                author_role="advisor",
            ),
        ),
        FixtureItem(
            id_hint="day01-apt",
            title="Apartment in Shin-Nakano · Night 1 of 4",
            starts_at=_at("2024-06-20", "21:00"),
            duration_minutes=540,
            attrs=HotelCardAttrs(
                name="Apartment in Shin-Nakano",
                location=SHIN_NAKANO,
                ambient_image="/japan/day01_apartment_shin_nakano.jpg",
                nights=4,
                night_bar=True,
                snapshot=CardSnapshot(
                    title="Apartment in Shin-Nakano",
                    cover_image="/japan/day01_apartment_shin_nakano.jpg",
                    location="Nakano-ku, Tokyo",
                    activities=["2 double beds", "One-bedroom unit"],
                ),
            ),
        ),
    ],
)


# ── Day 02 — Tokyo classics (sumo lunch + samurai studio) ────────────

ASAKUSA_STN = GeoPoint(lat=35.7106, lng=139.7975, label="Asakusa Station")
SENSO_JI = GeoPoint(lat=35.7148, lng=139.7967, label="Sensō-ji Temple")
SUMO_CLUB = GeoPoint(lat=35.7166, lng=139.7978, label="Asakusa Sumo Club")

DAY_02 = FixtureDay(
    date="2024-06-21",
    weather_emoji="☀",
    items=[
        FixtureItem(
            id_hint="day02-guide",
            title="Guide meets you at the apartment",
            starts_at=_at("2024-06-21", "07:40"),
            duration_minutes=25,
            attrs=NoteCardAttrs(
                body="Mr. Takebayashi Kei · 080-3094-0463",
                author_role="advisor",
            ),
        ),
        FixtureItem(
            id_hint="day02-tsukiji",
            title="Tsukiji Outer Market food tour",
            starts_at=_at("2024-06-21", "09:00"),
            duration_minutes=120,
            attrs=ExperienceCardAttrs(
                category="food_tour",
                location=GeoPoint(lat=35.6654, lng=139.7707, label="Tsukiji Outer Market"),
                energy_required=2,
                energy_after="neutral",
                snapshot=CardSnapshot(
                    title="Tsukiji Outer Market food tour",
                    location="Chuo-ku, Tokyo",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day02-sensoji",
            title="Sensō-ji & Nakamise-dori",
            starts_at=_at("2024-06-21", "11:00"),
            duration_minutes=60,
            attrs=ExperienceCardAttrs(
                category="cultural",
                location=SENSO_JI,
                energy_required=2,
                energy_after="neutral",
                snapshot=CardSnapshot(
                    title="Sensō-ji",
                    location="Asakusa, Taito-ku",
                    activities=["Kaminarimon", "Nakamise street snacks"],
                ),
            ),
        ),
        FixtureItem(
            id_hint="day02-sumo",
            title="Asakusa Sumo Club — chanko lunch + show",
            starts_at=_at("2024-06-21", "12:00"),
            duration_minutes=120,
            attrs=MealCardAttrs(
                cuisine_class="chanko-nabe",
                location=SUMO_CLUB,
                ambient_image="/japan/day02_asakusa_sumo_stable.jpg",
                description=("Chanko-nabe with retired sumo wrestlers plus a live show."),
                time_of_day="lunch",
                price="Included",
                seating_at=_at("2024-06-21", "12:00"),
                snapshot=CardSnapshot(
                    title="Asakusa Sumo Club",
                    cover_image="/japan/day02_asakusa_sumo_stable.jpg",
                    price="Included",
                    location="Asakusa",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day02-samurai",
            title="Samurai Sword & Ninja Experience",
            starts_at=_at("2024-06-21", "16:00"),
            duration_minutes=75,
            attrs=ExperienceCardAttrs(
                category="cultural",
                location=GeoPoint(lat=35.7104, lng=139.7970),
                ambient_image="/japan/day02_samurai_ninja_experience.jpg",
                description=(
                    "Order #S535502 · dress in samurai attire, katana handling, ninja demo."
                ),
                energy_required=2,
                gear_list=["Comfortable socks (worn over tabi)"],
                snapshot=CardSnapshot(
                    title="Samurai & Ninja Experience",
                    location="Asakusa",
                    activities=[
                        "Katana handling",
                        "Ninja demo",
                        "Samurai attire",
                    ],
                ),
            ),
        ),
    ],
)


# ── Day 05 — Shinkansen to Kyoto ──────────────────────────────────────

SHINAGAWA = GeoPoint(lat=35.6285, lng=139.7387, label="Shinagawa Station")
KYOTO = GeoPoint(lat=34.9859, lng=135.7585, label="Kyoto Station")

DAY_05 = FixtureDay(
    date="2024-06-24",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day05-shinkansen",
            title="Shinkansen Hikari #635 → Kyoto",
            starts_at=_at("2024-06-24", "08:40"),
            duration_minutes=153,
            attrs=TrainCardAttrs(
                from_station="Shinagawa",
                to_station="Kyoto",
                train_name="Hikari",
                train_number="635",
                from_location=SHINAGAWA,
                to_location=KYOTO,
                location=KYOTO,
                pass_eligibility=("JR Pass: Hikari covered; Nozomi/Mizuho not covered."),
                mode="JR Pass · reserved seats",
                description=("Hikari is covered by JR Pass; Nozomi/Mizuho are not."),
                depart_at=_at("2024-06-24", "08:40"),
                arrive_at=_at("2024-06-24", "11:13"),
                scenery_callouts=[
                    SceneryCallout(
                        # Mt Fuji visible ~minute 50 from Tokyo on the
                        # right (north) window of a southbound Shinkansen.
                        minute_offset=50,
                        side="right",
                        what="Mt. Fuji",
                    ),
                ],
            ),
        ),
        FixtureItem(
            id_hint="day05-bamboo",
            title="Arashiyama Bamboo Grove",
            starts_at=_at("2024-06-24", "12:30"),
            duration_minutes=90,
            attrs=ExperienceCardAttrs(
                category="nature",
                location=GeoPoint(lat=35.0170, lng=135.6717),
                ambient_image="/japan/day05_arashiyama_bamboo_grove.jpg",
                description="JR Sagano Line to Saga-Arashiyama, then walk.",
                energy_required=2,
                energy_after="restorative",
                snapshot=CardSnapshot(
                    title="Arashiyama Bamboo Grove",
                    cover_image="/japan/day05_arashiyama_bamboo_grove.jpg",
                    location="Ukyo-ku, Kyoto",
                ),
            ),
        ),
    ],
)


# ── Day 15 — departure ────────────────────────────────────────────────

SETAGAYA = GeoPoint(lat=35.6487, lng=139.5950, label="Soshigaya (Setagaya)")

DAY_15 = FixtureDay(
    date="2024-07-04",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day15-checkout",
            title="Check out of Setagaya apartment",
            starts_at=_at("2024-07-04", "10:00"),
            duration_minutes=60,
            attrs=NoteCardAttrs(author_role="advisor"),
        ),
        FixtureItem(
            id_hint="day15-train",
            title="Train → Haneda Airport",
            starts_at=_at("2024-07-04", "11:30"),
            duration_minutes=75,
            attrs=SubwayCardAttrs(
                from_location=SETAGAYA,
                to_location=HND,
                location=HND,
                mode="IC card · no JR Pass on final day",
                fare_or_pass_note="IC card only — JR Pass already returned",
            ),
        ),
        FixtureItem(
            id_hint="day15-departure",
            title="Depart Haneda · Delta DL276",
            starts_at=_at("2024-07-04", "15:25"),
            duration_minutes=30,
            attrs=FlightCardAttrs(
                iata_from="HND",
                iata_to="LAX",
                flight_code="DL276",
                from_location=HND,
                to_location=LAX,
                location=HND,
                tz_delta_hours=-16,
                depart_at=_at("2024-07-04", "15:25"),
            ),
        ),
    ],
)


JAPAN_DAYS: list[FixtureDay] = [DAY_01, DAY_02, DAY_05, DAY_15]


def all_items() -> list[FixtureItem]:
    """Flatten the fixture into one ordered list of items."""
    return [item for day in JAPAN_DAYS for item in day.items]


def metadata_dump(item: FixtureItem) -> dict[str, Any]:
    """Round-trip a fixture item's attrs through Pydantic's ``model_dump``
    so callers get the exact dict shape that would be persisted to
    ``nodes.metadata`` (jsonb). Drops ``None`` fields so the serialized
    blob stays compact.
    """
    return item.attrs.model_dump(exclude_none=True, mode="json")


__all__ = [
    "DAY_01",
    "DAY_02",
    "DAY_05",
    "DAY_15",
    "FixtureDay",
    "FixtureItem",
    "JAPAN_DAYS",
    "JST",
    "all_items",
    "metadata_dump",
]
