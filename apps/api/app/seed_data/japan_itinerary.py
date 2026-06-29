"""Real-trip Japan fixture for TravelGraph tests + the demo seeder.

A curated multi-city slice of a June 2024 Japan trip
(Tokyo → Kyoto → Hiroshima/Miyajima → Tokyo) used two ways:

1. As a **test fixture** — importing it validates every ``CardAttributes``
   constructor, so a schema constraint violation fails the import (the
   file is its own smoke test).
2. As the **demo seed** behind ``POST /demos/japan`` / ``ovb admin
   demo-japan`` — ``app/services/japan_template.py`` turns these days
   into a ``card_templates`` subgraph that instantiates into any
   client's account so the running app has a real, visualizable
   starter itinerary instead of an empty graph.

Design choices:

- **Every card kind is represented** so the seeded itinerary exercises
  the full card taxonomy the ``/prototype/cards`` design system renders
  (flight, subway, train, drive, walk, boat, hotel, experience, meal,
  free_time, waiting, note). The detail/zoom view leans on the
  signature fields populated here — train scenery callouts, subway line
  colours + transfers, "from your door" hotel walking distances, meal
  etiquette + pre-meal phrases, experience energy meters — so the cards
  look bespoke, not boilerplate.
- **Per-item ``status``** drives the substrate-weight card design: a
  confirmed flight visibly "weighs more" than a proposed idea. The
  template builder stamps this onto each node so the instantiated demo
  shows a realistic spread instead of a wall of identical proposals.
- ``starts_at`` is strictly increasing across the whole flattened list
  (within a day and across days) so the linearization service emits the
  cards in declared order.
- We use the granular Phase-1 ``NodeType`` values where the trip data
  indicates them (Shinkansen → ``train``, Tokyo Metro → ``subway``,
  private transfer → ``drive``, ferry → ``boat``).
- Each item is described with a Pydantic ``CardAttributes`` model so the
  fixture fails to load if a schema constraint is violated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.card_attrs import (
    BoatCardAttrs,
    CardAttributes,
    CardSnapshot,
    DriveCardAttrs,
    Driver,
    EtiquetteItem,
    ExperienceCardAttrs,
    FlightCardAttrs,
    FreeTimeCardAttrs,
    GeoPoint,
    HotelCardAttrs,
    MealCardAttrs,
    NoteCardAttrs,
    Phrase,
    SceneryCallout,
    SignageGloss,
    SubwayCardAttrs,
    SubwayLine,
    SubwayTransfer,
    TimeOfDayWindow,
    TrainCardAttrs,
    TrainStop,
    Vehicle,
    WaitingCardAttrs,
    WalkCardAttrs,
    WalkingDistance,
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

    ``status`` is the node's intended lifecycle state (one of the
    ``node_status`` enum values: idea / proposed / approved / booked /
    confirmed / discarded). The template builder carries it through so
    the seeded demo shows real status variety.
    """

    id_hint: str
    title: str
    starts_at: datetime
    duration_minutes: int
    attrs: CardAttributes
    status: str = "proposed"


@dataclass(frozen=True)
class FixtureDay:
    date: str
    weather_emoji: str | None
    items: list[FixtureItem] = field(default_factory=list)


# ── Shared geo points ─────────────────────────────────────────────────

HND = GeoPoint(lat=35.5494, lng=139.7798, label="Haneda Airport")
LAX = GeoPoint(lat=33.9416, lng=-118.4085, label="LAX")
SHIN_NAKANO = GeoPoint(lat=35.6930, lng=139.6662, label="Shin-Nakano")
TSUKIJI = GeoPoint(lat=35.6654, lng=139.7707, label="Tsukiji Outer Market")
ASAKUSA_STN = GeoPoint(lat=35.7106, lng=139.7975, label="Asakusa Station")
SENSO_JI = GeoPoint(lat=35.7148, lng=139.7967, label="Sensō-ji Temple")
SUMO_CLUB = GeoPoint(lat=35.7166, lng=139.7978, label="Asakusa Sumo Club")
SHINAGAWA = GeoPoint(lat=35.6285, lng=139.7387, label="Shinagawa Station")
KYOTO = GeoPoint(lat=34.9859, lng=135.7585, label="Kyoto Station")
ARASHIYAMA = GeoPoint(lat=35.0170, lng=135.6717, label="Arashiyama")
FUSHIMI_INARI = GeoPoint(lat=34.9671, lng=135.7727, label="Fushimi Inari Taisha")
GION = GeoPoint(lat=35.0037, lng=135.7752, label="Gion, Kyoto")
HIROSHIMA = GeoPoint(lat=34.3978, lng=132.4757, label="Hiroshima Station")
MIYAJIMAGUCHI = GeoPoint(lat=34.3119, lng=132.3036, label="Miyajimaguchi Pier")
MIYAJIMA = GeoPoint(lat=34.2959, lng=132.3197, label="Miyajima")
ITSUKUSHIMA = GeoPoint(lat=34.2960, lng=132.3199, label="Itsukushima Shrine")


# ── Day 01 — arrival in Tokyo ─────────────────────────────────────────

DAY_01 = FixtureDay(
    date="2024-06-20",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day01-arrival",
            title="Arrive Haneda — Delta DL275",
            starts_at=_at("2024-06-20", "16:10"),
            duration_minutes=30,
            status="confirmed",
            attrs=FlightCardAttrs(
                iata_from="LAX",
                iata_to="HND",
                flight_code="DL275",
                cabin="delta_one",
                seat="2A",
                terminal="3",
                gate="71",
                aircraft="Airbus A350-900",
                miles=5478,
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
                scenic_side="left",
                lounge_proximity="Sky Club at LAX · gate 71, 4 min walk",
                wifi="Free messaging · paid streaming",
                jet_lag_protocol=(
                    "Set your watch to Tokyo time at boarding. Sleep the first "
                    "6 hours, light meal on wake; a short daylight walk near "
                    "the apartment before dinner resets your clock."
                ),
                arrive_at=_at("2024-06-20", "16:10"),
            ),
        ),
        FixtureItem(
            id_hint="day01-immigration",
            title="Immigration & baggage buffer",
            starts_at=_at("2024-06-20", "16:45"),
            duration_minutes=40,
            status="approved",
            attrs=WaitingCardAttrs(
                location=HND,
                lounge_info="No lounge airside on arrival — proceed to immigration.",
                soft_progress_bar=True,
                use_this_time_to=[
                    "Open Visit Japan Web QR before the hall — it halves the queue",
                    "Withdraw ¥30,000 cash at the post-bank ATM past baggage claim",
                    "Activate the pocket Wi-Fi in your welcome pack",
                ],
                facilities=[
                    "Restrooms before passport control",
                    "Free water fountains by carousel 4",
                ],
            ),
        ),
        FixtureItem(
            id_hint="day01-assistant",
            title="Meet airport assistant at arrivals",
            starts_at=_at("2024-06-20", "17:30"),
            duration_minutes=15,
            status="confirmed",
            attrs=NoteCardAttrs(
                body=(
                    "Mr. Takebayashi Kei · 080-3094-0463. Holds a “Voyage” sign at "
                    "Arrivals Gate B. Hands over the IC card, validates the JR Pass, "
                    "and walks you to the car."
                ),
                author_name="Sarah (advisor)",
                author_role="advisor",
                visibility="shared",
                tags=["arrival", "ground-contact"],
            ),
        ),
        FixtureItem(
            id_hint="day01-transfer",
            title="Private car · Haneda → Shin-Nakano apartment",
            starts_at=_at("2024-06-20", "17:50"),
            duration_minutes=55,
            status="booked",
            attrs=DriveCardAttrs(
                eta_minutes=55,
                from_location=HND,
                to_location=SHIN_NAKANO,
                location=SHIN_NAKANO,
                bag_capacity=4,
                prior_trip_continuity=False,
                description=(
                    "Bayshore Route → Inner Circle. Light evening traffic; the "
                    "driver can detour past Tokyo Tower if you'd like a first look."
                ),
                vehicle=Vehicle(
                    make="Toyota Alphard Executive Lounge",
                    capacity=4,
                    plate="品川 330 あ 12-34",
                    plate_native_script="品川 330 あ 12-34",
                ),
                driver=Driver(
                    name="Hiroshi Tanaka",
                    languages=["EN", "JA"],
                    contact_link="tel:+819012345678",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day01-checkin",
            title="Apartment self-check-in",
            starts_at=_at("2024-06-20", "19:00"),
            duration_minutes=30,
            status="confirmed",
            attrs=NoteCardAttrs(
                body=(
                    "Assistant helps with the keybox self-check-in, then service "
                    "ends. Dinner excluded — convenience store two doors down."
                ),
                author_name="Sarah (advisor)",
                author_role="advisor",
                visibility="shared",
            ),
        ),
        FixtureItem(
            id_hint="day01-apt",
            title="Apartment in Shin-Nakano · Night 1 of 4",
            starts_at=_at("2024-06-20", "21:00"),
            duration_minutes=540,
            status="booked",
            attrs=HotelCardAttrs(
                name="Apartment in Shin-Nakano",
                room_type="One-bedroom · 2 double beds",
                nights=4,
                bedding="2 double beds",
                confirmation_number="ABNB-7741-NAK",
                location=SHIN_NAKANO,
                ambient_image="/japan/day01_apartment_shin_nakano.jpg",
                check_in=_at("2024-06-20", "19:00"),
                check_out=_at("2024-06-24", "10:00"),
                night_bar=True,
                in_room_amenities=["Washer/dryer", "Pocket Wi-Fi", "Nespresso", "Bath with reheat"],
                profile_prefs_honored=["High floor requested", "Quiet street side"],
                neighborhood_blurb=(
                    "Residential Nakano-ku — quiet at night, a 4-minute walk to the "
                    "Marunouchi Line and a covered shōtengai of izakaya and bakeries."
                ),
                walking_to=[
                    WalkingDistance(label="Shin-Nakano station", minutes=4, mode="covered"),
                    WalkingDistance(label="Nakano Broadway", minutes=11),
                    WalkingDistance(label="Lawson (24h)", minutes=1),
                ],
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


# ── Day 02 — Tokyo classics (sumo lunch + samurai studio) ─────────────

DAY_02 = FixtureDay(
    date="2024-06-21",
    weather_emoji="☀",
    items=[
        FixtureItem(
            id_hint="day02-guide",
            title="Guide meets you at the apartment",
            starts_at=_at("2024-06-21", "07:40"),
            duration_minutes=20,
            status="confirmed",
            attrs=NoteCardAttrs(
                body=(
                    "Mr. Takebayashi Kei · 080-3094-0463. Full-day private guide; "
                    "he carries the IC cards and handles every fare."
                ),
                author_name="Sarah (advisor)",
                author_role="advisor",
                visibility="shared",
                tags=["ground-contact"],
            ),
        ),
        FixtureItem(
            id_hint="day02-subway",
            title="Tokyo Metro · Shin-Nakano → Tsukiji",
            starts_at=_at("2024-06-21", "08:00"),
            duration_minutes=38,
            status="approved",
            attrs=SubwayCardAttrs(
                from_station="Shin-Nakano",
                to_station="Tsukijishijō",
                from_location=SHIN_NAKANO,
                to_location=TSUKIJI,
                location=TSUKIJI,
                mode="Tokyo Metro · IC card",
                fare_or_pass_note="¥210 IC · JR Pass not valid on Metro",
                lines=[
                    SubwayLine(name="Marunouchi", agency_color="#e60012"),
                    SubwayLine(name="Ōedo", agency_color="#b6007a"),
                ],
                transfers=[SubwayTransfer(station="Nakano-sakaue", line_color="#b6007a")],
                signage_gloss=[
                    SignageGloss(
                        native="築地市場",
                        romanization="Tsukiji-shijō",
                        traveler_lang="Tsukiji Market",
                    ),
                    SignageGloss(
                        native="出口 A1", romanization="Deguchi A1", traveler_lang="Exit A1"
                    ),
                ],
            ),
        ),
        FixtureItem(
            id_hint="day02-tsukiji",
            title="Tsukiji Outer Market food tour",
            starts_at=_at("2024-06-21", "09:00"),
            duration_minutes=120,
            status="approved",
            attrs=ExperienceCardAttrs(
                category="food_tour",
                location=TSUKIJI,
                ambient_image="/japan/day02_tsukiji_market.jpg",
                energy_required=2,
                energy_after="neutral",
                difficulty="Easy · lots of standing",
                best_window=TimeOfDayWindow(start_hour=8, end_hour=11),
                group_size="Private · up to 6",
                language_support="JA guide + live EN",
                gear_list=["Comfortable shoes", "Cash for stalls", "Empty stomach"],
                allergens=["shellfish", "soy"],
                weather_contingency="Covered arcade — runs rain or shine.",
                snapshot=CardSnapshot(
                    title="Tsukiji Outer Market food tour",
                    cover_image="/japan/day02_tsukiji_market.jpg",
                    location="Chuo-ku, Tokyo",
                    activities=["Tamagoyaki", "Uni & ikura", "Knife shops"],
                ),
            ),
        ),
        FixtureItem(
            id_hint="day02-sensoji",
            title="Sensō-ji & Nakamise-dōri",
            starts_at=_at("2024-06-21", "11:30"),
            duration_minutes=20,
            status="approved",
            attrs=WalkCardAttrs(
                distance_m=650,
                from_location=ASAKUSA_STN,
                to_location=SENSO_JI,
                location=SENSO_JI,
                description="Through Kaminarimon and up the souvenir street to the main hall.",
                surface_notes=["Flat paving", "Dense crowds near the gate", "Last 100 m cobbled"],
                pois_along=[
                    GeoPoint(lat=35.7113, lng=139.7965, label="Kaminarimon (Thunder Gate)"),
                    GeoPoint(lat=35.7128, lng=139.7966, label="Nakamise snack stalls"),
                ],
            ),
        ),
        FixtureItem(
            id_hint="day02-sumo",
            title="Asakusa Sumo Club — chanko lunch + show",
            starts_at=_at("2024-06-21", "12:00"),
            duration_minutes=120,
            status="booked",
            attrs=MealCardAttrs(
                cuisine_class="chanko-nabe",
                location=SUMO_CLUB,
                ambient_image="/japan/day02_asakusa_sumo_stable.jpg",
                description="Chanko-nabe with retired wrestlers, then a live demonstration bout.",
                time_of_day="lunch",
                price="Included",
                dress_code="Casual · floor seating (low table)",
                dietary_flags=["Pescatarian option on file", "Tree-nut allergy verified"],
                reservation_number="SUMO-2106-AC",
                cancellation_policy="48 hr · charged in full",
                seating_at=_at("2024-06-21", "12:00"),
                etiquette=[
                    EtiquetteItem(
                        label="Shoes off", body="Genkan at the entrance — socks provided."
                    ),
                    EtiquetteItem(
                        label="No photos mid-bout",
                        body="Photos welcome before and after the demonstration.",
                    ),
                    EtiquetteItem(
                        label="Ladle from the pot",
                        body="Serve others before yourself — it's the chanko way.",
                    ),
                ],
                pre_meal_phrases=[
                    Phrase(
                        native="いただきます",
                        romanization="itadakimasu",
                        gloss="said before eating",
                    ),
                    Phrase(
                        native="ごちそうさま", romanization="gochisōsama", gloss="said after eating"
                    ),
                ],
                snapshot=CardSnapshot(
                    title="Asakusa Sumo Club",
                    cover_image="/japan/day02_asakusa_sumo_stable.jpg",
                    price="Included",
                    location="Asakusa",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day02-free",
            title="Open afternoon · rest before the studio",
            starts_at=_at("2024-06-21", "14:30"),
            duration_minutes=75,
            status="proposed",
            attrs=FreeTimeCardAttrs(
                location=ASAKUSA_STN,
                weather="Clear · 27°C",
                energy_advice=(
                    "You've been on your feet since the market. A slow coffee and a "
                    "sit-down keeps energy for the samurai studio at 16:00."
                ),
                sunset=_at("2024-06-21", "19:00"),
                suggestion_grid=[
                    "Kissaten coffee at Angelus (6 min)",
                    "Sumida riverside bench",
                    "Browse Kappabashi kitchen street",
                ],
            ),
        ),
        FixtureItem(
            id_hint="day02-samurai",
            title="Samurai Sword & Ninja Experience",
            starts_at=_at("2024-06-21", "16:00"),
            duration_minutes=75,
            status="approved",
            attrs=ExperienceCardAttrs(
                category="cultural",
                location=GeoPoint(lat=35.7104, lng=139.7970, label="Asakusa studio"),
                ambient_image="/japan/day02_samurai_ninja_experience.jpg",
                description=(
                    "Order #S535502 · dress in samurai attire, katana handling, ninja demo."
                ),
                energy_required=2,
                energy_after="neutral",
                difficulty="Easy · standing",
                age_min=6,
                language_support="EN instructor",
                group_size="Private",
                gear_list=["Comfortable socks (worn over tabi)"],
                snapshot=CardSnapshot(
                    title="Samurai & Ninja Experience",
                    location="Asakusa",
                    activities=["Katana handling", "Ninja demo", "Samurai attire"],
                ),
            ),
        ),
    ],
)


# ── Day 05 — Shinkansen to Kyoto ──────────────────────────────────────

DAY_05 = FixtureDay(
    date="2024-06-24",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day05-shinkansen",
            title="Shinkansen Hikari #635 → Kyoto",
            starts_at=_at("2024-06-24", "08:40"),
            duration_minutes=153,
            status="approved",
            attrs=TrainCardAttrs(
                from_station="Shinagawa",
                to_station="Kyoto",
                train_name="Hikari",
                train_number="635",
                platform="23",
                car="8",
                seat="11A / 11B",
                from_location=SHINAGAWA,
                to_location=KYOTO,
                location=KYOTO,
                pass_eligibility="JR Pass: Hikari covered; Nozomi/Mizuho not covered.",
                mode="JR Pass · reserved seats",
                food_on_board="Ekiben at Shinagawa platform 23 — buy before boarding.",
                description="Hikari is covered by the JR Pass; Nozomi/Mizuho are not.",
                depart_at=_at("2024-06-24", "08:40"),
                arrive_at=_at("2024-06-24", "11:13"),
                stops=[
                    TrainStop(station="Shinagawa", departs_at=_at("2024-06-24", "08:40")),
                    TrainStop(
                        station="Shin-Yokohama",
                        arrives_at=_at("2024-06-24", "08:51"),
                        departs_at=_at("2024-06-24", "08:52"),
                    ),
                    TrainStop(
                        station="Nagoya",
                        arrives_at=_at("2024-06-24", "10:08"),
                        departs_at=_at("2024-06-24", "10:10"),
                    ),
                    TrainStop(station="Kyoto", arrives_at=_at("2024-06-24", "11:13")),
                ],
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
            starts_at=_at("2024-06-24", "11:30"),
            duration_minutes=90,
            status="approved",
            attrs=ExperienceCardAttrs(
                category="nature",
                location=ARASHIYAMA,
                ambient_image="/japan/day05_arashiyama_bamboo_grove.jpg",
                description="JR Sagano Line to Saga-Arashiyama, then a short walk into the grove.",
                energy_required=2,
                energy_after="restorative",
                difficulty="Easy · gentle slope",
                best_window=TimeOfDayWindow(start_hour=7, end_hour=10),
                weather_contingency="Atmospheric in light rain; bring the suite umbrella.",
                snapshot=CardSnapshot(
                    title="Arashiyama Bamboo Grove",
                    cover_image="/japan/day05_arashiyama_bamboo_grove.jpg",
                    location="Ukyo-ku, Kyoto",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day05-kaiseki",
            title="Kaiseki lunch · Kikunoi Roan",
            starts_at=_at("2024-06-24", "13:30"),
            duration_minutes=90,
            status="booked",
            attrs=MealCardAttrs(
                cuisine_class="kaiseki",
                location=GION,
                ambient_image="/japan/day05_kaiseki.jpg",
                time_of_day="lunch",
                price="¥¥¥¥",
                dress_code="Smart casual · no shorts",
                dietary_flags=["Pescatarian", "No land meat"],
                reservation_number="ROAN-2406-AC",
                cancellation_policy="72 hr · 100%",
                seating_at=_at("2024-06-24", "13:30"),
                etiquette=[
                    EtiquetteItem(
                        label="Eat in order", body="Courses are sequenced; eat each as it's placed."
                    ),
                    EtiquetteItem(
                        label="No fragrance", body="Scent competes with the seasonal dashi."
                    ),
                ],
                pre_meal_phrases=[
                    Phrase(
                        native="お任せします",
                        romanization="omakase shimasu",
                        gloss="I leave it to you",
                    ),
                    Phrase(
                        native="ごちそうさま", romanization="gochisōsama", gloss="said after eating"
                    ),
                ],
                snapshot=CardSnapshot(
                    title="Kikunoi Roan",
                    cover_image="/japan/day05_kaiseki.jpg",
                    price="¥¥¥¥",
                    location="Gion, Kyoto",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day05-fushimi",
            title="Fushimi Inari Taisha · torii path",
            starts_at=_at("2024-06-24", "15:30"),
            duration_minutes=120,
            status="proposed",
            attrs=ExperienceCardAttrs(
                category="cultural",
                location=FUSHIMI_INARI,
                ambient_image="/japan/day06_fushimi_inari_taisha.jpg",
                description=(
                    "The vermilion torii tunnels; quietest late afternoon as day-trippers leave."
                ),
                energy_required=4,
                energy_after="depleting",
                difficulty="Moderate · stairs to the summit (optional)",
                best_window=TimeOfDayWindow(start_hour=15, end_hour=18),
                gear_list=["Water", "Comfortable shoes"],
                snapshot=CardSnapshot(
                    title="Fushimi Inari Taisha",
                    cover_image="/japan/day06_fushimi_inari_taisha.jpg",
                    location="Fushimi-ku, Kyoto",
                    activities=["Senbon torii", "Summit loop (2 hr)"],
                ),
            ),
        ),
        FixtureItem(
            id_hint="day05-ryokan",
            title="Machiya ryokan · Gion · Night 1 of 3",
            starts_at=_at("2024-06-24", "21:00"),
            duration_minutes=540,
            status="confirmed",
            attrs=HotelCardAttrs(
                name="Sowaka",
                room_type="Machiya suite · garden view",
                nights=3,
                bedding="Futon on tatami · turn-down 20:00",
                confirmation_number="SOWAKA-KYO-55812",
                location=GION,
                ambient_image="/japan/day05_apartment_kyoto_resistay.jpg",
                check_in=_at("2024-06-24", "16:00"),
                check_out=_at("2024-06-27", "11:00"),
                night_bar=True,
                in_room_amenities=["Hinoki bath", "Yukata", "In-room tea service", "Garden engawa"],
                profile_prefs_honored=["Quiet inner room", "Vegetarian breakfast on file"],
                neighborhood_blurb=(
                    "Heart of Gion — lantern-lit Hanamikoji at your door, and the "
                    "Kamo river a 9-minute walk for an evening stroll."
                ),
                walking_to=[
                    WalkingDistance(label="Hanamikoji-dōri", minutes=2),
                    WalkingDistance(label="Kennin-ji temple", minutes=5),
                    WalkingDistance(label="Gion-Shijō station", minutes=10),
                ],
                snapshot=CardSnapshot(
                    title="Sowaka · Gion",
                    cover_image="/japan/day05_apartment_kyoto_resistay.jpg",
                    location="Higashiyama, Kyoto",
                    activities=["Machiya suite", "Hinoki bath"],
                ),
            ),
        ),
    ],
)


# ── Day 08 — Hiroshima & Miyajima (day trip) ──────────────────────────

DAY_08 = FixtureDay(
    date="2024-06-27",
    weather_emoji="⛅",
    items=[
        FixtureItem(
            id_hint="day08-shinkansen",
            title="Shinkansen Sakura #545 → Hiroshima",
            starts_at=_at("2024-06-27", "08:00"),
            duration_minutes=100,
            status="booked",
            attrs=TrainCardAttrs(
                from_station="Kyoto",
                to_station="Hiroshima",
                train_name="Sakura",
                train_number="545",
                platform="11",
                car="6",
                seat="3C / 3D",
                from_location=KYOTO,
                to_location=HIROSHIMA,
                location=HIROSHIMA,
                pass_eligibility="JR Pass: Sakura covered.",
                mode="JR Pass · reserved · 2+2 green-class seating",
                food_on_board="Anago-meshi ekiben recommended.",
                depart_at=_at("2024-06-27", "08:00"),
                arrive_at=_at("2024-06-27", "09:40"),
                stops=[
                    TrainStop(station="Kyoto", departs_at=_at("2024-06-27", "08:00")),
                    TrainStop(
                        station="Shin-Kobe",
                        arrives_at=_at("2024-06-27", "08:16"),
                        departs_at=_at("2024-06-27", "08:17"),
                    ),
                    TrainStop(
                        station="Okayama",
                        arrives_at=_at("2024-06-27", "08:54"),
                        departs_at=_at("2024-06-27", "08:56"),
                    ),
                    TrainStop(station="Hiroshima", arrives_at=_at("2024-06-27", "09:40")),
                ],
                scenery_callouts=[
                    SceneryCallout(minute_offset=42, side="right", what="Seto Inland Sea glimpses"),
                ],
            ),
        ),
        FixtureItem(
            id_hint="day08-ferry",
            title="JR ferry · Miyajimaguchi → Miyajima",
            starts_at=_at("2024-06-27", "10:30"),
            duration_minutes=12,
            status="approved",
            attrs=BoatCardAttrs(
                dock_from="Miyajimaguchi Pier",
                dock_to="Miyajima Pier",
                from_location=MIYAJIMAGUCHI,
                to_location=MIYAJIMA,
                location=MIYAJIMA,
                motion_sickness_rating="none",
                schedule_frequency="Every 15 min · JR Pass covers the JR ferry",
                description="Sit on the right deck outbound for the floating torii view.",
                bring_with=["IC card / JR Pass", "Light jacket — breeze on deck"],
            ),
        ),
        FixtureItem(
            id_hint="day08-itsukushima",
            title="Itsukushima Shrine & floating torii",
            starts_at=_at("2024-06-27", "11:00"),
            duration_minutes=120,
            status="approved",
            attrs=ExperienceCardAttrs(
                category="cultural",
                location=ITSUKUSHIMA,
                ambient_image="/japan/day08_itsukushima_shrine_torii.jpg",
                description=(
                    "Time the visit to high tide so the torii appears to float; deer roam freely."
                ),
                energy_required=2,
                energy_after="neutral",
                difficulty="Easy",
                best_window=TimeOfDayWindow(start_hour=10, end_hour=13),
                weather_contingency="Covered walkways through the shrine.",
                snapshot=CardSnapshot(
                    title="Itsukushima Shrine",
                    cover_image="/japan/day08_itsukushima_shrine_torii.jpg",
                    location="Miyajima, Hiroshima",
                    activities=["Floating torii", "Senjōkaku hall", "Free-roaming deer"],
                ),
            ),
        ),
        FixtureItem(
            id_hint="day08-okonomiyaki",
            title="Hiroshima okonomiyaki · Hassho",
            starts_at=_at("2024-06-27", "13:30"),
            duration_minutes=75,
            status="booked",
            attrs=MealCardAttrs(
                cuisine_class="okonomiyaki",
                location=HIROSHIMA,
                time_of_day="lunch",
                price="¥¥",
                dress_code="Casual · counter seating at the teppan",
                dietary_flags=["Can omit pork — tell the cook"],
                reservation_number="HASSHO-2706",
                seating_at=_at("2024-06-27", "13:30"),
                etiquette=[
                    EtiquetteItem(
                        label="Eat off the teppan",
                        body="Use the small spatula (hera); the griddle keeps it hot.",
                    ),
                ],
                pre_meal_phrases=[
                    Phrase(
                        native="いただきます",
                        romanization="itadakimasu",
                        gloss="said before eating",
                    ),
                ],
                snapshot=CardSnapshot(
                    title="Okonomiyaki Hassho",
                    price="¥¥",
                    location="Hiroshima",
                ),
            ),
        ),
    ],
)


# ── Day 15 — departure ────────────────────────────────────────────────

DAY_15 = FixtureDay(
    date="2024-07-04",
    weather_emoji="☁",
    items=[
        FixtureItem(
            id_hint="day15-checkout",
            title="Check out of Shin-Nakano apartment",
            starts_at=_at("2024-07-04", "10:00"),
            duration_minutes=45,
            status="confirmed",
            attrs=NoteCardAttrs(
                body=(
                    "Leave keys in the keybox; the cleaner confirms by 11:00. "
                    "Bins: combustible bag only."
                ),
                author_name="Sarah (advisor)",
                author_role="advisor",
                visibility="shared",
            ),
        ),
        FixtureItem(
            id_hint="day15-transfer",
            title="Private car · Shin-Nakano → Haneda",
            starts_at=_at("2024-07-04", "11:00"),
            duration_minutes=70,
            status="booked",
            attrs=DriveCardAttrs(
                eta_minutes=70,
                from_location=SHIN_NAKANO,
                to_location=HND,
                location=HND,
                bag_capacity=4,
                prior_trip_continuity=True,  # same driver as arrival
                description=(
                    "Same driver as your arrival transfer. Inner Circle → Bayshore "
                    "Route to Terminal 3 departures."
                ),
                vehicle=Vehicle(
                    make="Toyota Alphard Executive Lounge",
                    capacity=4,
                    plate="品川 330 あ 12-34",
                    plate_native_script="品川 330 あ 12-34",
                ),
                driver=Driver(
                    name="Hiroshi Tanaka",
                    languages=["EN", "JA"],
                    contact_link="tel:+819012345678",
                ),
            ),
        ),
        FixtureItem(
            id_hint="day15-buffer",
            title="Pre-flight buffer · Haneda",
            starts_at=_at("2024-07-04", "12:30"),
            duration_minutes=145,
            status="approved",
            attrs=WaitingCardAttrs(
                location=HND,
                lounge_info="Delta Sky Club · Terminal 3, near gate 110 · open",
                soft_progress_bar=True,
                use_this_time_to=[
                    "Eat real food before the cabin: Tsubohachi soba, T3 4F",
                    "Last currency exchange — keep cash for the taxi home",
                    "Refill water past security near gate 110",
                ],
                facilities=[
                    "Sky Club lounge",
                    "Family restroom past kiosk K3",
                    "Quiet mezzanine, north-east",
                ],
            ),
        ),
        FixtureItem(
            id_hint="day15-departure",
            title="Depart Haneda · Delta DL276",
            starts_at=_at("2024-07-04", "15:25"),
            duration_minutes=30,
            status="confirmed",
            attrs=FlightCardAttrs(
                iata_from="HND",
                iata_to="LAX",
                flight_code="DL276",
                cabin="delta_one",
                seat="2A",
                terminal="3",
                gate="110",
                aircraft="Airbus A350-900",
                miles=5478,
                from_location=HND,
                to_location=LAX,
                location=HND,
                tz_delta_hours=-16,
                scenic_side="right",
                lounge_proximity="Sky Club T3 · gate 110, 3 min walk",
                wifi="Free messaging · paid streaming",
                jet_lag_protocol=(
                    "Stay awake the first half; sleep the back third to land near LA morning."
                ),
                depart_at=_at("2024-07-04", "15:25"),
            ),
        ),
    ],
)


JAPAN_DAYS: list[FixtureDay] = [DAY_01, DAY_02, DAY_05, DAY_08, DAY_15]


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
    "DAY_08",
    "DAY_15",
    "FixtureDay",
    "FixtureItem",
    "JAPAN_DAYS",
    "JST",
    "all_items",
    "metadata_dump",
]
