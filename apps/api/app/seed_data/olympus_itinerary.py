"""Mt Olympus / Greece campaign spine — length-variant seed fixture.

Backs the ``olympus`` campaign (see :mod:`app.campaigns.registry`). A single
14-day day-list authored here is sliced by :mod:`app.services.olympus_template`
into three shipped spines — 5, 7, and 14 nights — so the dashboard kickoff can
snap the traveler's chosen dates to the nearest length and drop a right-sized
skeleton onto their fork.

The days are ordered so any prefix is a coherent trip:

- **first 5** — arrive, base at Litochoro, acclimatize in the Enipeas gorge,
  ascend to the Spilios Agapitos refuge, summit Mytikas, and come down to the
  coast. A complete ascent-and-down.
- **first 7** — add the Dion archaeological park and a second Olympian Riviera
  day: the mountain plus its mythic foothills.
- **all 14** — the grand tour: Meteora, Vergína, Pelion, and the wine country
  of the north.

Every item is a Pydantic ``CardAttributes`` model, so a schema violation fails
the import — the fixture is its own smoke test, exactly like the Japan seed.
Return flights and the airport ground-transfer are intentionally NOT here: the
agent adds those live (the transfer via the real Google-Routes ``add_transfer``
capability), which is part of the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.card_attrs import (
    ExperienceCardAttrs,
    FlightCardAttrs,
    FreeTimeCardAttrs,
    GeoPoint,
    HotelCardAttrs,
    MealCardAttrs,
    TrainCardAttrs,
)
from app.seed_data.japan_itinerary import FixtureDay, FixtureItem

# Greece summer is EEST (+03:00).
EEST = timezone(timedelta(hours=3))


def _at(date_iso: str, hhmm: str) -> datetime:
    """Compose a tz-aware datetime in EEST."""
    h, m = (int(part) for part in hhmm.split(":", 1))
    y, mo, d = (int(part) for part in date_iso.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=EEST)


# ── Shared geo points ─────────────────────────────────────────────────

SKG = GeoPoint(lat=40.5197, lng=22.9709, label="Thessaloniki Airport (SKG)")
LITOCHORO = GeoPoint(lat=40.1008, lng=22.5011, label="Litochoro")
ENIPEAS = GeoPoint(lat=40.0872, lng=22.4358, label="Enipeas Gorge")
PRIONIA = GeoPoint(lat=40.0872, lng=22.3775, label="Prionia trailhead")
REFUGE = GeoPoint(lat=40.0869, lng=22.3597, label="Spilios Agapitos refuge")
MYTIKAS = GeoPoint(lat=40.0885, lng=22.3489, label="Mytikas summit")
RIVIERA = GeoPoint(lat=40.1667, lng=22.5833, label="Olympian Riviera")
DION = GeoPoint(lat=40.1731, lng=22.4931, label="Dion Archaeological Park")
METEORA = GeoPoint(lat=39.7217, lng=21.6306, label="Meteora")
VERGINA = GeoPoint(lat=40.4894, lng=22.3186, label="Vergína (Aigai)")
PELION = GeoPoint(lat=39.4000, lng=23.1000, label="Mount Pelion")
NAOUSSA = GeoPoint(lat=40.6289, lng=22.0678, label="Naoussa wine country")


# Anchor: start-of-day on the arrival date, EEST.
TRIP_ANCHOR = datetime(2026, 9, 14, 0, 0, tzinfo=EEST)


def _hotel(name: str, nights: int, loc: GeoPoint, blurb: str) -> HotelCardAttrs:
    return HotelCardAttrs(
        nights=nights, name=name, neighborhood_blurb=blurb, location=loc, night_bar=True
    )


# ── The 14-day day-list (any prefix is a coherent trip) ────────────────

OLYMPUS_DAYS: list[FixtureDay] = [
    # Day 01 — arrive Thessaloniki, train south to Litochoro, base camp.
    FixtureDay(
        date="2026-09-14",
        weather_emoji="☀",
        items=[
            FixtureItem(
                id_hint="d01-arrive",
                title="Arrive Thessaloniki (SKG)",
                starts_at=_at("2026-09-14", "13:30"),
                duration_minutes=45,
                status="confirmed",
                attrs=FlightCardAttrs(iata_to="SKG", to_location=SKG, location=SKG),
            ),
            FixtureItem(
                id_hint="d01-train",
                title="Rail south to Litochoro",
                starts_at=_at("2026-09-14", "16:00"),
                duration_minutes=70,
                status="approved",
                attrs=TrainCardAttrs(from_location=SKG, to_location=LITOCHORO),
            ),
            FixtureItem(
                id_hint="d01-hotel",
                title="Check in — Litochoro base",
                starts_at=_at("2026-09-14", "18:00"),
                duration_minutes=60,
                status="booked",
                attrs=_hotel(
                    "Villa Drosos",
                    4,
                    LITOCHORO,
                    "Stone rooms at the mountain's foot, olive terrace, Mytikas on the skyline.",
                ),
            ),
        ],
    ),
    # Day 02 — acclimatize in the Enipeas gorge; taverna dinner.
    FixtureDay(
        date="2026-09-15",
        weather_emoji="⛅",
        items=[
            FixtureItem(
                id_hint="d02-gorge",
                title="Enipeas Gorge acclimatization hike",
                starts_at=_at("2026-09-15", "08:30"),
                duration_minutes=300,
                status="approved",
                attrs=ExperienceCardAttrs(
                    category="hiking", difficulty="moderate", energy_required=3, location=ENIPEAS
                ),
            ),
            FixtureItem(
                id_hint="d02-dinner",
                title="Taverna dinner in Litochoro",
                starts_at=_at("2026-09-15", "20:00"),
                duration_minutes=120,
                status="pending",
                attrs=MealCardAttrs(cuisine_class="taverna", location=LITOCHORO),
            ),
        ],
    ),
    # Day 03 — Prionia trailhead up to the Spilios Agapitos refuge.
    FixtureDay(
        date="2026-09-16",
        weather_emoji="🌤",
        items=[
            FixtureItem(
                id_hint="d03-ascend",
                title="Prionia → Spilios Agapitos refuge",
                starts_at=_at("2026-09-16", "09:00"),
                duration_minutes=210,
                status="approved",
                attrs=ExperienceCardAttrs(
                    category="trekking", difficulty="strenuous", energy_required=4, location=PRIONIA
                ),
            ),
            FixtureItem(
                id_hint="d03-refuge",
                title="Overnight — Refuge A (Spilios Agapitos)",
                starts_at=_at("2026-09-16", "17:00"),
                duration_minutes=60,
                status="booked",
                attrs=_hotel(
                    "Refuge A · Spilios Agapitos",
                    1,
                    REFUGE,
                    "The classic hut at 2,100 m — bunks, hearty dinner, an alpine start.",
                ),
            ),
        ],
    ),
    # Day 04 — summit Mytikas, descend to the refuge.
    FixtureDay(
        date="2026-09-17",
        weather_emoji="🌄",
        items=[
            FixtureItem(
                id_hint="d04-summit",
                title="Summit Mytikas (2,918 m)",
                starts_at=_at("2026-09-17", "06:00"),
                duration_minutes=420,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="mountaineering",
                    difficulty="strenuous",
                    energy_required=5,
                    location=MYTIKAS,
                ),
            ),
            FixtureItem(
                id_hint="d04-refuge",
                title="Second night at the refuge",
                starts_at=_at("2026-09-17", "18:00"),
                duration_minutes=60,
                status="pending",
                attrs=_hotel(
                    "Refuge A · Spilios Agapitos",
                    1,
                    REFUGE,
                    "Back to the hut, legs earned, for the last night on the mountain.",
                ),
            ),
        ],
    ),
    # Day 05 — descend to Litochoro, recover on the Olympian Riviera.
    FixtureDay(
        date="2026-09-18",
        weather_emoji="☀",
        items=[
            FixtureItem(
                id_hint="d05-descend",
                title="Descend to Litochoro",
                starts_at=_at("2026-09-18", "08:30"),
                duration_minutes=240,
                status="approved",
                attrs=ExperienceCardAttrs(
                    category="hiking", difficulty="moderate", energy_required=3, location=LITOCHORO
                ),
            ),
            FixtureItem(
                id_hint="d05-riviera",
                title="Recovery afternoon — Olympian Riviera",
                starts_at=_at("2026-09-18", "16:00"),
                duration_minutes=180,
                status="pending",
                attrs=FreeTimeCardAttrs(
                    energy_advice="Feet up, sea swim, long dinner — you've summited.",
                    location=RIVIERA,
                ),
            ),
        ],
    ),
    # Day 06 — Dion, the sacred city at the mountain's foot.
    FixtureDay(
        date="2026-09-19",
        weather_emoji="🏛",
        items=[
            FixtureItem(
                id_hint="d06-dion",
                title="Dion Archaeological Park",
                starts_at=_at("2026-09-19", "10:00"),
                duration_minutes=180,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture", difficulty="easy", energy_required=1, location=DION
                ),
            ),
            FixtureItem(
                id_hint="d06-hotel",
                title="Check in — Riviera seafront",
                starts_at=_at("2026-09-19", "15:00"),
                duration_minutes=60,
                status="pending",
                attrs=_hotel(
                    "Aegean Blue",
                    3,
                    RIVIERA,
                    "Seafront rooms on the Riviera, mountain behind you, water at the door.",
                ),
            ),
        ],
    ),
    # Day 07 — a slow Riviera day.
    FixtureDay(
        date="2026-09-20",
        weather_emoji="🏖",
        items=[
            FixtureItem(
                id_hint="d07-beach",
                title="Olympian Riviera — a slow day",
                starts_at=_at("2026-09-20", "11:00"),
                duration_minutes=300,
                status="pending",
                attrs=FreeTimeCardAttrs(
                    energy_advice="Nothing on the plan but the sea.", location=RIVIERA
                ),
            ),
        ],
    ),
    # Day 08 — Meteora, the monasteries in the sky.
    FixtureDay(
        date="2026-09-21",
        weather_emoji="⛰",
        items=[
            FixtureItem(
                id_hint="d08-meteora",
                title="Meteora — monasteries in the sky",
                starts_at=_at("2026-09-21", "09:00"),
                duration_minutes=420,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture", difficulty="easy", energy_required=2, location=METEORA
                ),
            ),
        ],
    ),
    # Day 09 — Vergína, the royal tombs of Macedon.
    FixtureDay(
        date="2026-09-22",
        weather_emoji="🏺",
        items=[
            FixtureItem(
                id_hint="d09-vergina",
                title="Vergína — royal tombs of Aigai",
                starts_at=_at("2026-09-22", "10:00"),
                duration_minutes=180,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture", difficulty="easy", energy_required=1, location=VERGINA
                ),
            ),
        ],
    ),
    # Day 10 — wine country of Naoussa.
    FixtureDay(
        date="2026-09-23",
        weather_emoji="🍇",
        items=[
            FixtureItem(
                id_hint="d10-wine",
                title="Naoussa wine country",
                starts_at=_at("2026-09-23", "11:00"),
                duration_minutes=240,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="food_wine", difficulty="easy", energy_required=1, location=NAOUSSA
                ),
            ),
        ],
    ),
    # Day 11 — transfer to Pelion.
    FixtureDay(
        date="2026-09-24",
        weather_emoji="🌲",
        items=[
            FixtureItem(
                id_hint="d11-pelion",
                title="Into the Pelion villages",
                starts_at=_at("2026-09-24", "14:00"),
                duration_minutes=120,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="scenic", difficulty="easy", energy_required=1, location=PELION
                ),
            ),
            FixtureItem(
                id_hint="d11-hotel",
                title="Check in — Pelion mansion",
                starts_at=_at("2026-09-24", "17:00"),
                duration_minutes=60,
                status="pending",
                attrs=_hotel(
                    "Archontiko Pelion",
                    3,
                    PELION,
                    "A restored stone mansion in the chestnut forest above the Pagasetic gulf.",
                ),
            ),
        ],
    ),
    # Day 12 — Pelion trails to the sea.
    FixtureDay(
        date="2026-09-25",
        weather_emoji="🥾",
        items=[
            FixtureItem(
                id_hint="d12-trail",
                title="Cobbled trail down to Damouchari",
                starts_at=_at("2026-09-25", "09:30"),
                duration_minutes=240,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="hiking", difficulty="moderate", energy_required=3, location=PELION
                ),
            ),
        ],
    ),
    # Day 13 — a last slow day.
    FixtureDay(
        date="2026-09-26",
        weather_emoji="☕",
        items=[
            FixtureItem(
                id_hint="d13-slow",
                title="A slow last day in the villages",
                starts_at=_at("2026-09-26", "11:00"),
                duration_minutes=240,
                status="pending",
                attrs=FreeTimeCardAttrs(
                    energy_advice="Coffee in the platía, a long lunch, no agenda.", location=PELION
                ),
            ),
        ],
    ),
    # Day 14 — back north toward Thessaloniki.
    FixtureDay(
        date="2026-09-27",
        weather_emoji="🚉",
        items=[
            FixtureItem(
                id_hint="d14-north",
                title="North to Thessaloniki",
                starts_at=_at("2026-09-27", "10:00"),
                duration_minutes=180,
                status="pending",
                attrs=TrainCardAttrs(from_location=PELION, to_location=SKG),
            ),
            FixtureItem(
                id_hint="d14-hotel",
                title="Check in — Thessaloniki waterfront",
                starts_at=_at("2026-09-27", "16:00"),
                duration_minutes=60,
                status="pending",
                attrs=_hotel(
                    "Excelsior Thessaloniki",
                    1,
                    SKG,
                    "A last night on the waterfront before you fly home.",
                ),
            ),
        ],
    ),
]


__all__ = ["OLYMPUS_DAYS", "TRIP_ANCHOR"]
