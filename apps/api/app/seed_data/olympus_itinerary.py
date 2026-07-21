"""Mt Olympus / Greece campaign spine — cornerstone-led seed fixture.

Backs the ``olympus`` campaign (see :mod:`app.campaigns.registry`). The spine is
composed at build time (:mod:`app.services.olympus_template`) from three parts so
the mountain is told ONCE — by the real OV cornerstone trip — and never
double-booked by hand-authored cards:

1. **Arrival** — day 1 is a held travel-day NOTE, nothing else. It tells the
   traveler the day is reserved for the journey in and that flights are shaped
   in conversation once we know their origin. A note (not a free_time block)
   so the kernel never reads it as a commitment the inbound flight must beat.
2. **The cornerstone** — the real, bookable OV adventure (Path to Symbolism for
   the long spine, the 2-Day Summit push for the short ones). Its day-by-day
   itinerary is materialized as a SUBGRAPH whose children lay across the mountain
   days as the itinerary's experiences (see ``olympus_template``). This is the
   ONLY mountain content — there are deliberately no hand-authored gorge / refuge
   / summit / descend cards competing with it.
3. **The extension** — the grand tour AFTER the guided ascent (Riviera, Dion,
   Meteora, wine country, Pelion). Authored relative to its own day 0 and shifted
   by the cornerstone's span at build time, then prefix-sliced to fill whatever
   nights remain. Any prefix is a coherent extension.

So a 14-night trip = a travel day + a 6-day guided ascent + a 7-day grand tour;
a 7-night = travel + the 2-day summit push + a 4-day tour; a 5-night = travel +
the push + a 2-day tour. The mountain days carry the cornerstone's beats and
only the beats.

Every item is a Pydantic ``CardAttributes`` model, so a schema violation fails
the import — the fixture is its own smoke test, exactly like the Japan seed.
Flights (inbound and return) and the airport ground-transfer are intentionally
NOT here: we don't know the traveler's origin, so the agent proposes those live
in conversation (the transfer via the real Google-Routes ``add_transfer``
capability), which is part of the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.card_attrs import (
    CardSnapshot,
    ExperienceCardAttrs,
    FreeTimeCardAttrs,
    GalleryImage,
    GeoPoint,
    HotelCardAttrs,
    NoteCardAttrs,
)
from app.seed_data.japan_itinerary import FixtureDay, FixtureItem

# Greece summer is EEST (+03:00).
EEST = timezone(timedelta(hours=3))


def _img(photo_id: str, *, w: int = 1600, q: int = 80) -> str:
    """An Unsplash CDN url for a bare ``photo-…`` id (host allowlisted in
    ``next.config.ts``). Mirrors the mood-frame convention in ``lib/atmos``."""
    return f"https://images.unsplash.com/{photo_id}?w={w}&q={q}&auto=format&fit=crop"


def _gallery(*pairs: tuple[str, str]) -> list[GalleryImage]:
    """Build a ``(photo_id, credit)`` list into thumbnail gallery images."""
    return [GalleryImage(url=_img(pid, w=900, q=70), credit=credit) for pid, credit in pairs]


def _at(date_iso: str, hhmm: str) -> datetime:
    """Compose a tz-aware datetime in EEST."""
    h, m = (int(part) for part in hhmm.split(":", 1))
    y, mo, d = (int(part) for part in date_iso.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=EEST)


# ── Shared geo points ─────────────────────────────────────────────────

SKG = GeoPoint(lat=40.5197, lng=22.9709, label="Thessaloniki Airport (SKG)")
THESSALONIKI = GeoPoint(lat=40.6293, lng=22.9464, label="Thessaloniki")
LITOCHORO = GeoPoint(lat=40.1008, lng=22.5011, label="Litochoro")
RIVIERA = GeoPoint(lat=40.1667, lng=22.5833, label="Olympian Riviera")
DION = GeoPoint(lat=40.1731, lng=22.4931, label="Dion Archaeological Park")
METEORA = GeoPoint(lat=39.7217, lng=21.6306, label="Meteora")
PELION = GeoPoint(lat=39.4000, lng=23.1000, label="Mount Pelion")
NAOUSSA = GeoPoint(lat=40.6289, lng=22.0678, label="Naoussa wine country")


# Anchor: start-of-day on the arrival date, EEST. Trip day 1 = this instant; the
# extension day-list below is authored from the SAME anchor (its own day 0) and
# shifted by the cornerstone's span at build time.
TRIP_ANCHOR = datetime(2026, 9, 14, 0, 0, tzinfo=EEST)


def _hotel(name: str, nights: int, loc: GeoPoint, blurb: str) -> HotelCardAttrs:
    return HotelCardAttrs(
        nights=nights, name=name, neighborhood_blurb=blurb, location=loc, night_bar=True
    )


# ── Part 1: arrival (day 1) ────────────────────────────────────────────
# Day 1 is deliberately EMPTY of itinerary content: a single margin NOTE
# saying the day is reserved for travel. We don't know where the traveler
# flies from, so no inbound flight (or airport transfer) is seeded — the agent
# proposes those in conversation, and this note says exactly that.
#
# Deliberately a ``note``, NOT a ``free_time`` card: notes are annotations,
# not event commitments, so the kernel's flight floor (``_EVENT_TYPES`` in
# app/kernel/analysis.py) ignores it. A timed free_time block here made the
# 09:00 "Travel day" the trip's first commitment and forced every proposed
# inbound flight to land before it — the day exists to RECEIVE the flight,
# not to fence it out. Zero duration → the note anchors the day as an
# open instant, never a block. The guided ascent begins the next morning
# (the builder shifts the cornerstone and the extension one day down to
# make room).

ARRIVAL_ITEMS: list[FixtureItem] = [
    FixtureItem(
        id_hint="d01-travel",
        title="Travel day — held for your arrival",
        starts_at=_at("2026-09-14", "09:00"),
        duration_minutes=0,
        status="pending",
        attrs=NoteCardAttrs(
            location=LITOCHORO,
            description=(
                "This first day is held open for travel. We don't yet know where "
                "you'll be flying from — tell us and we'll shape the flights, and "
                "the drive down to the mountain, around your door. Nothing on "
                "this day is booked until you say so."
            ),
        ),
    ),
]


# ── Part 3: the extension grand tour (authored from its own day 0) ─────
# Shifted by the cornerstone's span at build time, then prefix-sliced to fill the
# nights left after the guided ascent. Ordered so any prefix reads coherently:
# recover on the Riviera, the mythic foothills (Dion), then the wider grand tour.

EXTENSION_DAYS: list[FixtureDay] = [
    # Ext day 1 — recover on the coast; move to the seafront base.
    FixtureDay(
        date="2026-09-14",
        weather_emoji="☀",
        items=[
            FixtureItem(
                id_hint="ext-riviera",
                title="Recovery day — Olympian Riviera",
                starts_at=_at("2026-09-14", "11:00"),
                duration_minutes=300,
                status="pending",
                attrs=FreeTimeCardAttrs(
                    energy_advice="Feet up, sea swim, long dinner — you've summited.",
                    location=RIVIERA,
                    ambient_image=_img("photo-1629286521404-77161a73af35"),
                    description=(
                        "The long exhale after the summit. Blue-flag beaches unspool along the "
                        "Pierian coast beneath Olympus itself — swim in the Thermaic Gulf, nap "
                        "under a tamarisk, and let a seaside taverna stretch dinner past sunset."
                    ),
                ),
            ),
            FixtureItem(
                id_hint="ext-riviera-hotel",
                title="Check in — Riviera seafront",
                starts_at=_at("2026-09-14", "16:00"),
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
    # Ext day 2 — Dion, the sacred city at the mountain's foot.
    FixtureDay(
        date="2026-09-15",
        weather_emoji="🏛",
        items=[
            FixtureItem(
                id_hint="ext-dion",
                title="Dion Archaeological Park",
                starts_at=_at("2026-09-15", "10:00"),
                duration_minutes=180,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture",
                    difficulty="easy",
                    energy_required=1,
                    location=DION,
                    ambient_image=_img("photo-1507475380673-1246fa72eeea"),
                    description=(
                        "The sacred city where Macedonian kings sacrificed to Olympian Zeus "
                        "before marching to war. Wander marble streets, the sanctuary of Isis, "
                        "and a Hellenistic theatre — mosaics and toppled columns half-swallowed "
                        "by wetland reeds at the mountain's foot."
                    ),
                    snapshot=CardSnapshot(
                        title="Dion Archaeological Park",
                        cover_image=_img("photo-1507475380673-1246fa72eeea"),
                        location="Dion, Pieria",
                        difficulty="Easy",
                    ),
                    gallery=_gallery(
                        ("photo-1697455621587-1011833b931c", "Dawid Tkocz"),
                        ("photo-1603566541830-972ff1b4b2cd", "Constantinos Kollias"),
                    ),
                ),
            ),
        ],
    ),
    # Ext day 3 — Meteora, the monasteries in the sky.
    FixtureDay(
        date="2026-09-16",
        weather_emoji="⛰",
        items=[
            FixtureItem(
                id_hint="ext-meteora",
                title="Meteora — monasteries in the sky",
                starts_at=_at("2026-09-16", "09:00"),
                duration_minutes=420,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture",
                    difficulty="easy",
                    energy_required=2,
                    location=METEORA,
                    ambient_image=_img("photo-1495386217358-4ffdde036fe7"),
                    description=(
                        "Byzantine monasteries perched on sheer sandstone pillars hundreds of "
                        "metres above the Thessalian plain. Six still-active retreats cling to "
                        "the rock; the drive between them, and the light at dawn, are among the "
                        "most otherworldly sights in all of Greece."
                    ),
                    snapshot=CardSnapshot(
                        title="Meteora",
                        cover_image=_img("photo-1495386217358-4ffdde036fe7"),
                        location="Kalambaka, Thessaly",
                        difficulty="Easy",
                    ),
                    gallery=_gallery(
                        ("photo-1552482496-3c03befc5c25", "George Tasios"),
                        ("photo-1672643344999-5c92165cefd7", "Hendrik Morkel"),
                    ),
                ),
            ),
        ],
    ),
    # Ext day 4 — wine country of Naoussa.
    FixtureDay(
        date="2026-09-17",
        weather_emoji="🍇",
        items=[
            FixtureItem(
                id_hint="ext-wine",
                title="Naoussa wine country",
                starts_at=_at("2026-09-17", "11:00"),
                duration_minutes=240,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="food_wine",
                    difficulty="easy",
                    energy_required=1,
                    location=NAOUSSA,
                    ambient_image=_img("photo-1585867313424-06b0fd07d314"),
                    description=(
                        "The heartland of Xinomavro, Greece's great age-worthy red. Tour family "
                        "estates on the slopes of Mount Vermio, taste barrel to bottle, and lunch "
                        "long over local charcuterie and the region's famous peaches."
                    ),
                    snapshot=CardSnapshot(
                        title="Naoussa wine country",
                        cover_image=_img("photo-1585867313424-06b0fd07d314"),
                        location="Naoussa, Imathia",
                        difficulty="Easy",
                    ),
                    gallery=_gallery(
                        ("photo-1588157138186-e801edd25c2b", "Dmitry Ant"),
                        ("photo-1712560357606-5696232746a5", "Divya Kothari"),
                    ),
                ),
            ),
        ],
    ),
    # Ext day 5 — into the Pelion villages; change base.
    FixtureDay(
        date="2026-09-18",
        weather_emoji="🌲",
        items=[
            FixtureItem(
                id_hint="ext-pelion",
                title="Into the Pelion villages",
                starts_at=_at("2026-09-18", "14:00"),
                duration_minutes=120,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="scenic",
                    difficulty="easy",
                    energy_required=1,
                    location=PELION,
                    ambient_image=_img("photo-1596562307805-d136e6ef40ba"),
                    description=(
                        "The mythic home of the centaurs — a green mountain of cobbled lanes, "
                        "plane-shaded squares, and stone mansions above the Pagasetic Gulf. "
                        "Settle into a restored archontiko as the chestnut forests turn."
                    ),
                    snapshot=CardSnapshot(
                        title="Mount Pelion villages",
                        cover_image=_img("photo-1596562307805-d136e6ef40ba"),
                        location="Pelion, Magnesia",
                    ),
                    gallery=_gallery(("photo-1759063295341-3fa9bccbe006", "Nikos Kavvadas")),
                ),
            ),
            FixtureItem(
                id_hint="ext-pelion-hotel",
                title="Check in — Pelion mansion",
                starts_at=_at("2026-09-18", "17:00"),
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
    # Ext day 6 — Pelion trails to the sea.
    FixtureDay(
        date="2026-09-19",
        weather_emoji="🥾",
        items=[
            FixtureItem(
                id_hint="ext-trail",
                title="Cobbled trail down to Damouchari",
                starts_at=_at("2026-09-19", "09:30"),
                duration_minutes=240,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="hiking",
                    difficulty="moderate",
                    energy_required=3,
                    location=PELION,
                    ambient_image=_img("photo-1782820057276-3e6c38bdc600"),
                    description=(
                        "A centuries-old kalderimi threads down through olive groves and oak to "
                        "Damouchari, a tiny pebble cove on the Aegean. Easy underfoot and all "
                        "downhill, ending with a swim off the rocks where Mamma Mia! was filmed."
                    ),
                    snapshot=CardSnapshot(
                        title="Kalderimi to Damouchari",
                        cover_image=_img("photo-1782820057276-3e6c38bdc600"),
                        location="Damouchari, Pelion",
                        difficulty="Moderate",
                    ),
                    gallery=_gallery(
                        ("photo-1758384265478-9deff5c5a77d", "Luis Gonçalves"),
                        ("photo-1761236246445-ddc075864919", "Ludovico Ceroseis"),
                    ),
                ),
            ),
        ],
    ),
    # Ext day 7 — a last slow day in the villages.
    FixtureDay(
        date="2026-09-20",
        weather_emoji="☕",
        items=[
            FixtureItem(
                id_hint="ext-slow",
                title="A slow day in the villages",
                starts_at=_at("2026-09-20", "11:00"),
                duration_minutes=240,
                status="pending",
                attrs=FreeTimeCardAttrs(
                    energy_advice="Coffee in the platía, a long lunch, no agenda.",
                    location=PELION,
                    ambient_image=_img("photo-1601581875039-e899893d520c"),
                    description=(
                        "No agenda but the platía. A slow Greek coffee under the plane tree, a "
                        "wander between village bakeries, a long lunch, an afternoon that goes "
                        "nowhere on purpose."
                    ),
                ),
            ),
        ],
    ),
    # Ext day 8 — the grand tour closes in Thessaloniki, the north's capital.
    # Deliberately NO train / airport run / "fly home" framing: we don't know
    # when or how the traveler departs, so that leg is proposed live in
    # conversation, never seeded (same rule as the missing inbound flight).
    FixtureDay(
        date="2026-09-21",
        weather_emoji="🌆",
        items=[
            FixtureItem(
                id_hint="ext-thessaloniki",
                title="Thessaloniki — the northern capital",
                starts_at=_at("2026-09-21", "12:00"),
                duration_minutes=300,
                status="pending",
                attrs=ExperienceCardAttrs(
                    category="culture",
                    difficulty="easy",
                    energy_required=1,
                    location=THESSALONIKI,
                    ambient_image=_img("photo-1766261010715-f5c230be72f7"),
                    description=(
                        "The grand tour closes in the north's capital — the White Tower, the "
                        "waterfront promenade, Byzantine walls above the old town, and an "
                        "evening given over to the city's celebrated food."
                    ),
                    snapshot=CardSnapshot(
                        title="Thessaloniki",
                        cover_image=_img("photo-1766261010715-f5c230be72f7"),
                        location="Thessaloniki, Macedonia",
                        difficulty="Easy",
                    ),
                ),
            ),
            FixtureItem(
                id_hint="ext-thessaloniki-hotel",
                title="Check in — Thessaloniki waterfront",
                starts_at=_at("2026-09-21", "16:00"),
                duration_minutes=60,
                status="pending",
                attrs=_hotel(
                    "Excelsior Thessaloniki",
                    1,
                    THESSALONIKI,
                    "Seafront rooms on the Thermaic Gulf, the White Tower a stroll away.",
                ),
            ),
        ],
    ),
]


__all__ = [
    "ARRIVAL_ITEMS",
    "EXTENSION_DAYS",
    "TRIP_ANCHOR",
]
