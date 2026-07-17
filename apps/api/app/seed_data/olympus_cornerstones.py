"""Real Outdoor Voyage trips that anchor the Mt Olympus campaign spines.

Each Olympus spine (see :mod:`app.seed_data.olympus_itinerary`) is built around
a real, bookable OV adventure — its *cornerstone*. The template builder
(:mod:`app.services.olympus_template`) enriches the spine's summit experience
node with the cornerstone's cover (the card hero), full image gallery,
description, and headline price so the demo shows genuine Olympus photography
and a real trip behind the curated skeleton.

The two cornerstones map to trip length:

- **14-night (the longest)** → *Trip to Mount Olympus – The Path to Symbolism*
  (operator "Mountain Path", 6-day guided ascent Litochoro → Mytikas). This is
  also the source of the campaign hero image (``imageUrl`` of the ``olympus``
  mood in ``apps/web/lib/atmos/moods.ts``).
- **5- and 7-night (the shorter pushes)** → *Guided Hiking Trip to Olympus
  Summit – 2 Days* (an overnight refuge-to-Mytikas summit push).

The image URLs, descriptions, and prices were pulled from the live OV API
(``GET /api/trips/{id}``) at authoring time and baked in as constants: the
template builder runs at cold start and in the offline test suite, so it must
stay deterministic and network-free (mirroring the static Japan template, not
the live ``japan_live`` build). Re-pull with the trip ids below to refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.inventory.schemas import ItineraryDay, Location
from app.models import NodeType


@dataclass(frozen=True)
class CornerstoneBeat:
    """One inferred moment within a cornerstone day — a virtual sub-node.

    The vendor writes each day as one prose paragraph; the beats break that
    paragraph into the moments it actually narrates (morning coffee, the royal
    tomb, the hot bath, dinner at the guesthouse) so the day reads as a lived
    sequence on the calendar instead of a single flat card. Times and durations
    are INFERRED at authoring time — editorial scheduling, not vendor data.
    """

    #: Local start time within the day, ``"HH:MM"`` (EEST — the trip's zone).
    hhmm: str
    title: str
    #: Card kind for this moment. The vendor writes every day as prose, but the
    #: beats it narrates are not all the same kind of thing: a dinner is a
    #: ``meal``, a coach transfer is a ``drive``, an unstructured morning is
    #: ``free_time``. Defaults to ``experience`` (the hikes, sights, and swims
    #: that make up most of a day) so only the exceptions need to be declared.
    node_type: NodeType = NodeType.experience
    duration_minutes: int = 60
    #: Short editorial description, derived from the vendor's day prose.
    description: str | None = None
    #: :data:`BEAT_STOCK` category this beat's imagery comes from. Repeated
    #: categories within one cornerstone rotate through the set, so three
    #: dinners get three different shots. None → the parent's gallery rotation.
    stock: str | None = None
    #: Optional per-beat geo point. A beat normally inherits its parent day's
    #: lat/lng, but a beat that happens somewhere else within the day (e.g. a
    #: transit that starts at a distant transit hub) overrides it here so the
    #: card pins — and its "open in Maps" button lands — at the right spot.
    lat: float | None = None
    lng: float | None = None
    location_label: str | None = None


@dataclass(frozen=True)
class CornerstoneDay:
    """One day of a cornerstone trip's internal itinerary.

    Baked from the OV trip's ``itineraries[].days[]`` (``GET /api/trips/{id}``),
    the same source the live from-inventory path reads. These become the summit
    node's subgraph children so the anchor card reads as the real multi-day OV
    adventure it is — an expandable day-by-day journey, not a single photo card.
    When a day ships ``beats``, each beat becomes its OWN child laid onto the
    day at its inferred time; a beat-less day falls back to the single
    day-child the inventory-born path produces.
    """

    #: 1-based day index within the trip.
    day: int
    title: str
    #: Active hours on the trail, when the vendor states them (OV ``hours``).
    hours: float | None = None
    #: Plain-text day description (vendor HTML stripped at authoring time).
    description: str | None = None
    #: Day geo point from the OV payload's ``days[].location`` (lat/lng).
    lat: float | None = None
    lng: float | None = None
    #: Human place label for the day (authored; OV's ``place`` is empty).
    location_label: str | None = None
    #: The day's inferred sub-moments, in chronological order.
    beats: tuple[CornerstoneBeat, ...] = field(default_factory=tuple)

    def as_itinerary_day(self) -> ItineraryDay:
        """This day as :class:`ItineraryDay` — the provider-shaped view."""
        location = (
            Location(lat=self.lat, lng=self.lng, label=self.location_label)
            if self.lat is not None or self.lng is not None or self.location_label
            else None
        )
        return ItineraryDay(
            day=self.day,
            title=self.title,
            description=self.description,
            hours=self.hours,
            location=location,
        )


@dataclass(frozen=True)
class OlympusCornerstone:
    """A real OV adventure that anchors a length-variant Olympus spine."""

    #: OV trip id (GET /api/trips/{trip_id}) the data below was pulled from.
    trip_id: str
    #: outdoorvoyage.com/adventures/{slug} — the public trip page.
    slug: str
    title: str
    #: Public CDN cover image — becomes the anchor card's hero (``ambient_image``
    #: + ``snapshot.cover_image``).
    cover_image: str
    #: Public CDN gallery URLs (OV ``images[]``) — the card's "moments" strip.
    gallery_urls: tuple[str, ...]
    #: Plain-text trip description (HTML stripped) shown on the card.
    description: str
    #: Headline "from" price, native currency (OV ``minPrice``).
    price_label: str
    #: Human difficulty label (OV ``difficulty`` on a 1–10 scale).
    difficulty: str
    location_label: str
    #: Local start time of the anchor card on day 1 (``"HH:MM"``, EEST) — the
    #: full ascent starts mid-afternoon (day 1 is the airport pickup); the
    #: 2-day push meets at Litochoro's parking lot at 10:00 sharp.
    anchor_hhmm: str = "15:00"
    #: The trip's internal day-by-day itinerary — baked from OV, materialized as
    #: the summit node's subgraph children (see :func:`itinerary_days`).
    days: tuple[CornerstoneDay, ...] = field(default_factory=tuple)

    def itinerary_days(self) -> list[ItineraryDay]:
        """The cornerstone's days as :class:`ItineraryDay`, subgraph-ready.

        Same shape the OV provider emits from a live detail fetch, so the
        template builder can feed these through the shared subgraph-metadata
        builder and the children render identically to an inventory-born
        multi-day card. Day geo comes from the OV payload's per-day
        ``location`` (baked at authoring time).
        """
        return [d.as_itinerary_day() for d in self.days]

    def enrichment(self) -> dict[str, Any]:
        """Card-attrs fragment merged onto the spine's summit experience node.

        Every key is a valid :class:`~app.schemas.card_attrs.ExperienceCardAttrs`
        field, so the merged metadata round-trips cleanly through
        ``parse_card_attrs`` on read. Merged over (not replacing) the fixture
        card's ``category`` / ``difficulty`` / ``energy_required`` / ``location``.
        """
        return {
            "ambient_image": self.cover_image,
            "description": self.description,
            "snapshot": {
                "title": self.title,
                "cover_image": self.cover_image,
                "price": self.price_label,
                "location": self.location_label,
                "difficulty": self.difficulty,
            },
            "gallery": [{"url": url} for url in self.gallery_urls],
            # The vetted operator behind every Olympus cornerstone. Rendered as
            # the detail card's "specially vetted" seal, linking to the operator
            # profile page under the web app's public/ tree.
            "operator": {
                "name": "Trekking Hellas",
                "logo_url": "/operators/trekking-hellas/logo-header.svg",
                "profile_url": "/operators/trekking-hellas",
                "vetted": True,
            },
        }


_OV_CDN = "https://cdn-pub.prod.outdoorvoyage.com"


def _stock_img(photo_id: str) -> str:
    """An Unsplash CDN url for a bare ``photo-…`` id (host allowlisted in
    ``next.config.ts``) — same convention as the Olympus extension fixture."""
    return f"https://images.unsplash.com/{photo_id}?w=1600&q=80&auto=format&fit=crop"


#: Curated stock imagery for beat sub-cards, keyed by the kind of moment. Every
#: id was pulled from an Unsplash search at authoring time and visually vetted
#: (2026-07). Sets are ordered best-fit-first: the template builder walks a
#: cornerstone's beats and rotates through a category's set in this order, so
#: the first beat of a kind gets the set's strongest match and repeats stay
#: varied. 3–5 images per set.
BEAT_STOCK: dict[str, tuple[str, ...]] = {
    # Coffee with a view — alpine mug first (day-4 plateau breakfast), then
    # the valley-balcony shots (day-5 "balcony of Olympus").
    "coffee-view": (
        _stock_img("photo-1760197161667-bb3b063ef63b"),
        _stock_img("photo-1577885215340-742f4551d417"),
        _stock_img("photo-1677490240383-c98c6b5f5732"),
        _stock_img("photo-1782139186009-6fcc4f2326ea"),
        _stock_img("photo-1768347440174-5bd817400f0f"),
    ),
    "breakfast": (
        _stock_img("photo-1647797658735-a33e305946ec"),
        _stock_img("photo-1780403919362-90a8a0b8527d"),
        _stock_img("photo-1731013449350-6f5d8f31d3e1"),
    ),
    "taverna": (
        _stock_img("photo-1602591546738-ceab3d349681"),
        _stock_img("photo-1602008394120-5cc61b4f6ada"),
        _stock_img("photo-1602348143971-0c5c97d23367"),
        _stock_img("photo-1658742758848-e9496d31a8b6"),
        _stock_img("photo-1469532954151-60b475900aa2"),
    ),
    "refuge": (
        _stock_img("photo-1652451489139-e160b7dff1b4"),
        _stock_img("photo-1781095249833-b484c67f9832"),
        _stock_img("photo-1724170856329-3bc5c57c6ab6"),
        _stock_img("photo-1604092815195-db1759a549b4"),
        _stock_img("photo-1775122739880-228d8fd86304"),
    ),
    "headlamp": (
        _stock_img("photo-1761566704064-796a21037500"),
        _stock_img("photo-1770793624380-a33a5ac8875d"),
        _stock_img("photo-1758300245541-a2804f1b3f3d"),
        _stock_img("photo-1704801467339-8a00f9e1712c"),
    ),
    "scramble": (
        _stock_img("photo-1765338023080-ee6b3abf8044"),
        _stock_img("photo-1764014936889-9be94965694d"),
        _stock_img("photo-1777205001357-92022f02a3cd"),
    ),
    # Meadow-under-the-peak first (the climb), the rock towers second (the
    # Throne of Zeus), then the gentler plateau moods.
    "plateau": (
        _stock_img("photo-1582694976769-2f1986650549"),
        _stock_img("photo-1494625927555-6ec4433b1571"),
        _stock_img("photo-1690022344181-b147209ecc84"),
        _stock_img("photo-1764093141154-1a85db6e7c63"),
    ),
    "chapel": (
        _stock_img("photo-1773869910347-f1fd6a08b704"),
        _stock_img("photo-1766500030507-b3968cb95f19"),
        _stock_img("photo-1647243032440-ae6f32720273"),
        _stock_img("photo-1658728480944-961aa28aae94"),
    ),
    "monastery": (
        _stock_img("photo-1769034323392-35a8308aa7e9"),
        _stock_img("photo-1759668559362-6892d06b90c3"),
        _stock_img("photo-1769034313410-4a96f1fe4d26"),
    ),
    "gorge": (
        _stock_img("photo-1775549197189-c8629e1a5e79"),
        _stock_img("photo-1698837245593-542584dc727d"),
        _stock_img("photo-1761420723548-63998866767c"),
        _stock_img("photo-1783611066000-721ec4b32254"),
        _stock_img("photo-1762279993578-5c214b969360"),
    ),
    "museum": (
        _stock_img("photo-1762140079845-786817904a53"),
        _stock_img("photo-1775057194807-f97e2080c797"),
        _stock_img("photo-1782466357373-515da25d313e"),
        _stock_img("photo-1775057194819-762ad1503709"),
        _stock_img("photo-1776799733252-e918015c662b"),
    ),
    "gold": (
        _stock_img("photo-1643893246704-2859bebfa6a9"),
        _stock_img("photo-1737478914352-feb9265dcf7c"),
        _stock_img("photo-1643893267404-74bbdb694c5c"),
        _stock_img("photo-1697851791965-584a7df40b54"),
    ),
    "thermal": (
        _stock_img("photo-1781458650999-78d7f722c187"),
        _stock_img("photo-1519320993082-43a535317ddc"),
        _stock_img("photo-1508869184489-1b42faa950b0"),
    ),
    # Real Litochoro / Enipeas-mouth photography.
    "village": (
        _stock_img("photo-1754606492081-4eccdd842dcf"),
        _stock_img("photo-1698837245535-aa9eb6fd9678"),
        _stock_img("photo-1754324114044-dd25fceae288"),
        _stock_img("photo-1698837246144-916cd738fbd0"),
    ),
    "drive": (
        _stock_img("photo-1594025598467-4b9941e5f420"),
        _stock_img("photo-1536420100273-cabfa8e5b67a"),
        _stock_img("photo-1635965453398-121ed3ea7c24"),
        _stock_img("photo-1775649136027-eec8b7c2eb71"),
        _stock_img("photo-1623784569334-26770407d2a4"),
    ),
    "gear": (
        _stock_img("photo-1485809052957-5113b0ff51af"),
        _stock_img("photo-1499803270242-467f7311582d"),
        _stock_img("photo-1476979735039-2fdea9e9e407"),
        _stock_img("photo-1592388748465-8c4dca8dd703"),
    ),
    "sunset": (
        _stock_img("photo-1697222564092-f4dab603efa8"),
        _stock_img("photo-1551384745-01b8c3f3fd41"),
        _stock_img("photo-1697222564085-6c3a135d0b46"),
        _stock_img("photo-1697222564107-2ea14363f70d"),
        _stock_img("photo-1726853550443-20b90f727b9b"),
    ),
    "forest": (
        _stock_img("photo-1780887079131-15ee680f2d2d"),
        _stock_img("photo-1763202366900-7c52f71d9cdb"),
        _stock_img("photo-1600818596647-9d5318c20a8a"),
        _stock_img("photo-1766005193305-aec0d7f3e74e"),
    ),
}


# ── The longest spine's cornerstone: the full guided ascent ────────────
SYMBOLISM = OlympusCornerstone(
    trip_id="018f39f5-7050-7b2c-a1c4-0c689797f113",
    slug="trip-to-mount-olympus-the-path-to-symbolism",
    title="Trip to Mount Olympus — The Path to Symbolism",
    cover_image=(
        f"{_OV_CDN}/operators/018f395d-288e-777c-a64d-3808a193b686"
        "/adventures/018f39f5-7050-7b2c-a1c4-0c689797f113/covers/6kTOaS42q124.jpg"
    ),
    gallery_urls=tuple(
        f"{_OV_CDN}/operators/018f395d-288e-777c-a64d-3808a193b686"
        f"/trips/018f39f5-7050-7b2c-a1c4-0c689797f113/images/{name}.jpg"
        for name in (
            "4gnvYacw48p5",
            "A5v9yk02kVgr",
            "50yEF0QAcypr",
            "U33dwrH3KYi0",
            "R4R9rihofg5A",
            "tZRxmIQ1sZqg",
            "hD5zfIYYtrPp",
            "f5ubDH5LXnex",
            "xVMqslnvADKj",
        )
    ),
    description=(
        "Mount Olympus, in northeast Greece, has been known as the home of Zeus "
        "and the major Greek gods since before the time of Homer. It rises almost "
        "straight from the Aegean Sea to a height of 2,917 meters, making it the "
        "tallest mountain in Greece. Its lower slopes are broken by narrow, "
        "densely forested gorges marked by waterfalls and caves where lesser gods "
        "and spirits were said to live; its 52 separate peaks are snow-capped for "
        "eight months of the year and often hidden in the clouds. On this journey "
        "we explore the culture, history, gastronomy, and lush nature of the area, "
        "starting from the village of Litochoro at the mountain's foot and hiking "
        "all the way up to the Mytikas peak — the throne of Zeus — staying in "
        "mountain refuges along the way."
    ),
    price_label="from €1,280",
    difficulty="6/10 — strenuous",
    location_label="Mount Olympus, Greece",
    days=(
        CornerstoneDay(
            day=1,
            title="Meet your guide",
            lat=40.10154,
            lng=22.50168,
            location_label="Litochoro",
            description=(
                "Your guide meets you at arrivals and the mountain takes over "
                "from there — an easy drive south along the coast, Olympus "
                "growing on the horizon."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="16:00",
                    title="Transit From Thessaloniki to Litochoro",
                    node_type=NodeType.drive,
                    stock="drive",
                    duration_minutes=60,
                    # Anchored at Thessaloniki's central rail/coach interchange —
                    # the southbound departure point for Litochoro (which sits on
                    # the same line). Pins the transit's origin so we can price the
                    # airport → station leg once the traveler's flight is known,
                    # whether they run straight from arrivals or overnight nearby.
                    lat=40.6441,
                    lng=22.9316,
                    location_label="Thessaloniki New Railway Station",
                    description=(
                        "Your guide meets you at arrivals and the mountain takes over "
                        "from there — an easy drive south along the coast, Olympus "
                        "growing on the horizon."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="17:00",
                    title="Settle into Litochoro",
                    stock="village",
                    duration_minutes=60,
                    description=(
                        "The stone village at the foot of the gods' massif — plane "
                        "trees, mountain water in the lanes, and the Enipeas gorge "
                        "opening straight above the rooftops."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="19:30",
                    title="Welcome dinner in the village",
                    node_type=NodeType.meal,
                    stock="taverna",
                    duration_minutes=120,
                    description=(
                        "A long table, local wine, and the plan for the days ahead. "
                        "Overnight in Litochoro — tomorrow the mountain begins."
                    ),
                ),
            ),
        ),
        CornerstoneDay(
            day=2,
            title="National Park museum and Enipeas River",
            lat=40.10264,
            lng=22.50236,
            location_label="Litochoro & the Enipeas gorge",
            description=(
                "We visit the National Park museum for a virtual ascent from the "
                "foothills to the top of the mountain, learning the history, flora, "
                "and fauna of Olympus. We find the place where the cause of the "
                "Trojan war began, hear local myths and tales, and — for the brave "
                "— swim in the crystal-clear, freezing waters of the Enipeas river. "
                "The day ends at the old monastery of Saint Dionysios and the cave "
                "where he lived as a hermit. Dinner and overnight in Litochoro."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="08:00",
                    title="Breakfast in Litochoro",
                    node_type=NodeType.meal,
                    stock="breakfast",
                    duration_minutes=60,
                    description="Village bakery breakfast before an easy first day.",
                ),
                CornerstoneBeat(
                    hhmm="09:30",
                    title="National Park museum — the mountain in miniature",
                    stock="museum",
                    duration_minutes=90,
                    description=(
                        "A virtual ascent from the foothills to the summits: the "
                        "history, flora, and fauna of Olympus before you walk into it."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="11:30",
                    title="Enipeas gorge — myths and a brave swim",
                    stock="gorge",
                    duration_minutes=150,
                    description=(
                        "The place where the cause of the Trojan war began, local "
                        "myths and tales — and for the brave, a dive into the "
                        "crystal-clear, freezing pools of the Enipeas."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="15:00",
                    title="Monastery of Saint Dionysios & the hermit's cave",
                    stock="monastery",
                    duration_minutes=120,
                    description=(
                        "The old monastery deep in the gorge, and the cave where "
                        "the saint lived out his hermit years."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="19:30",
                    title="Dinner & overnight — Litochoro",
                    node_type=NodeType.meal,
                    stock="taverna",
                    duration_minutes=120,
                    description="Last village comforts before the refuges.",
                ),
            ),
        ),
        CornerstoneDay(
            day=3,
            title="Apostolidis refuge",
            lat=40.09492,
            lng=22.36144,
            location_label="Muses Plateau",
            description=(
                "Our goal is the Muses Plateau. We pass the Ithakisios cave, where "
                "the great painter lived for more than 15 years, and the old "
                "shepherds' settlement. After a light lunch at Petrostrouga refuge "
                "we climb three more hours to the Muses Plateau, standing at last "
                "before the Throne of Zeus. Dinner and overnight in Apostolidis "
                "Refuge."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="07:30",
                    title="Breakfast & pack for the refuges",
                    node_type=NodeType.meal,
                    stock="gear",
                    duration_minutes=60,
                    description="Bags down to essentials — two nights on the mountain.",
                ),
                CornerstoneBeat(
                    hhmm="09:00",
                    title="Up the mountain — Ithakisios cave",
                    stock="forest",
                    duration_minutes=210,
                    description=(
                        "Through the forest past the cave where the painter "
                        "Ithakisios lived for fifteen years, and the old shepherds' "
                        "settlement above it."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="12:30",
                    title="Light lunch — Petrostrouga refuge",
                    node_type=NodeType.meal,
                    stock="refuge",
                    duration_minutes=60,
                    description="Recharge under the Bosnian pines.",
                ),
                CornerstoneBeat(
                    hhmm="13:30",
                    title="The climb to the Muses Plateau",
                    stock="plateau",
                    duration_minutes=180,
                    description=(
                        "Three more hours up, out of the trees and into the alpine light."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="16:30",
                    title="Before the Throne of Zeus",
                    stock="plateau",
                    duration_minutes=60,
                    description=(
                        "Standing at last on the plateau of the Muses, the summit "
                        "wall rising ahead."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="19:00",
                    title="Dinner & overnight — Apostolidis refuge",
                    node_type=NodeType.meal,
                    stock="refuge",
                    duration_minutes=120,
                    description="Refuge supper, alpine night, an early alarm.",
                ),
            ),
        ),
        CornerstoneDay(
            day=4,
            title="Mytikas summit & Petrostrouga Refuge",
            lat=40.10942,
            lng=22.41329,
            location_label="Mytikas summit",
            description=(
                "Today we climb to the Mytikas summit, for those who want and can. "
                "The whole group can visit Profitis Ilias summit and its chapel — "
                "the highest in the Balkans. After some free time we begin the "
                "descent before sunset to Petrostrouga Refuge. Dinner and overnight "
                "in Petrostrouga Refuge."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="06:30",
                    title="Alpine breakfast on the plateau",
                    node_type=NodeType.meal,
                    stock="coffee-view",
                    duration_minutes=60,
                    description="First light on the Aegean, coffee at altitude.",
                ),
                CornerstoneBeat(
                    hhmm="07:30",
                    title="Summit morning — Mytikas",
                    stock="scramble",
                    duration_minutes=270,
                    description=(
                        "The climb to the throne of Zeus, for those who want and "
                        "can — the highest point in Greece."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="12:30",
                    title="Profitis Ilias — the highest chapel in the Balkans",
                    stock="chapel",
                    duration_minutes=90,
                    description=(
                        "The whole group can stand at the tiny stone chapel on its own summit."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="14:30",
                    title="Free hours on the roof of Greece",
                    node_type=NodeType.free_time,
                    stock="plateau",
                    duration_minutes=120,
                    description="Unhurried time among the peaks before the descent.",
                ),
                CornerstoneBeat(
                    hhmm="16:30",
                    title="Descent to Petrostrouga before sunset",
                    stock="sunset",
                    duration_minutes=150,
                    description="Down through the golden hour to the treeline refuge.",
                ),
                CornerstoneBeat(
                    hhmm="19:30",
                    title="Dinner & overnight — Petrostrouga refuge",
                    node_type=NodeType.meal,
                    stock="refuge",
                    duration_minutes=120,
                    description="Summit stories over a refuge table.",
                ),
            ),
        ),
        CornerstoneDay(
            day=5,
            title="Vergina and Aridea",
            lat=40.49126,
            lng=22.31272,
            location_label="Vergina & Aridaia",
            description=(
                "We wake to coffee on the finest balcony of Mount Olympus, with "
                "panoramic views over the Thermaikos gulf and the Pieria Riviera. "
                "From Gortsia we head to Vergina and the royal tomb of Philip II — "
                "father of Alexander the Great — and close the day soaking in an "
                "outdoor hot bath in the Aridaia region. Dinner and overnight in a "
                "guesthouse."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="07:30",
                    title="Coffee on the balcony of Olympus",
                    node_type=NodeType.meal,
                    stock="coffee-view",
                    duration_minutes=60,
                    description=(
                        "Morning coffee on the finest balcony of the mountain — "
                        "panoramic views over the Thermaikos gulf and the whole "
                        "Pieria Riviera."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="09:00",
                    title="Down the mountain to Gortsia",
                    stock="forest",
                    duration_minutes=90,
                    description="The last descent — trailhead, boots off, wheels on.",
                ),
                CornerstoneBeat(
                    hhmm="11:00",
                    title="Vergina — the royal tomb of Philip II",
                    stock="gold",
                    duration_minutes=150,
                    description=(
                        "The tomb of the great king of the Macedonians, father of "
                        "Alexander the Great — gold larnax, oak-leaf crown, and the "
                        "burial mound entire."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="15:30",
                    title="Outdoor hot baths — Aridaia",
                    stock="thermal",
                    duration_minutes=150,
                    description=(
                        "The end of the day finds you soaking in an outdoor thermal "
                        "bath in the Aridaia region — five days of mountain worked "
                        "out of the shoulders."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="20:00",
                    title="Dinner & overnight — a countryside guesthouse",
                    node_type=NodeType.meal,
                    stock="taverna",
                    duration_minutes=120,
                    description="A guesthouse table in the spa country.",
                ),
            ),
        ),
        CornerstoneDay(
            day=6,
            title="Thessaloniki Airport",
            lat=40.52012,
            lng=22.97207,
            location_label="Thessaloniki Airport",
            description=(
                "Depending on your departure time we adapt the schedule (a final "
                "visit and so on) and then take you back to Thessaloniki Airport."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="09:00",
                    title="A last morning breakfast in the countryside",
                    node_type=NodeType.meal,
                    stock="breakfast",
                    duration_minutes=120,
                    description=("A slow breakfast, one more look at the mountain."),
                ),
                CornerstoneBeat(
                    hhmm="11:00",
                    title="Return to Thessaloniki",
                    node_type=NodeType.drive,
                    stock="drive",
                    duration_minutes=90,
                    description=(
                        "Back along the coast to the same transit terminal you departed from."
                    ),
                    lat=40.6441,
                    lng=22.9316,
                ),
            ),
        ),
    ),
)


# ── The shorter spines' cornerstone: the overnight summit push ──────────
GUIDED_2DAY = OlympusCornerstone(
    trip_id="0194f2c4-1ea8-70c0-988d-feaf74a870b4",
    slug="guided-hiking-trip-to-olympus-summit-2-days",
    title="Guided Hiking Trip to Olympus Summit — 2 Days",
    cover_image=(
        f"{_OV_CDN}/operators/0194f2c3-5b4e-73be-93f3-28a74b42ad4b"
        "/adventures/0194f2c4-1ea8-70c0-988d-feaf74a870b4/covers/7mvAelxU2pJ1.jpg"
    ),
    gallery_urls=tuple(
        f"{_OV_CDN}/operators/0194f2c3-5b4e-73be-93f3-28a74b42ad4b"
        f"/adventures/0194f2c4-1ea8-70c0-988d-feaf74a870b4/images/{name}.jpg"
        for name in (
            "TyPC4NPoF3W0",
            "3J1iT8R6gHqD",
            "PttPppDjLmDQ",
            "HStRbdCCXpYv",
            "gS8qS52yGb5q",
            "KpILCJdDo9HK",
            "LnzS7jWokh90",
            "VNmKvmX0YgRr",
            "9YntqIBwcbX1",
            "7yllgfdyLVRK",
            "SQAbPMrnK8YW",
            "Eq7vb5uIJ2Dd",
        )
    ),
    description=(
        "Climbing to the summit of Mount Olympus is a must-do for any adventurer "
        "visiting Greece. As the highest peak in the country, Mytikas "
        "(2,918 m / 9,574 ft) offers a unique blend of mythological significance "
        "and natural beauty. On this 2-day guided trek we make our way to the top "
        "of Mytikas with an overnight stay at the Spilios Agapitos hut: the first "
        "day eases into the mountain's dramatic landscape, and the second "
        "culminates in an exhilarating summit push aided by an expert guide and "
        "the necessary climbing equipment. From lush forests to rocky ridgelines "
        "to breathtaking panoramic views at the summit, you experience Olympus in "
        "its full glory — and learn the ancient myths that make it a legendary place."
    ),
    price_label="from €210",
    difficulty="7/10 — strenuous",
    location_label="Mount Olympus, Greece",
    #: The vendor's own meet time — day 1 begins at Litochoro's parking lot.
    anchor_hhmm="10:00",
    days=(
        CornerstoneDay(
            day=1,
            title="Litochoro – Prionia – Spilios Agapitos Hut",
            hours=4.0,
            lat=40.08108,
            lng=22.35256,
            location_label="Prionia → Spilios Agapitos refuge",
            description=(
                "We meet around 10:00 at Litochoro's central parking lot for an "
                "equipment check and briefing, then drive to the Prionia trailhead "
                "(1,100 m). From there we hike the most popular path on Olympus — "
                "part of the E4 European trail — climbing steadily through shady "
                "forest and towering Bosnian pines to the Spilios Agapitos refuge "
                "(2,100 m): about 5.5 km and +1,000 m over roughly 3–3.5 hours. At "
                "the hut we enjoy a warm meal, rest, and prepare for summit day."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="10:00",
                    title="Meet in Litochoro — gear check & briefing",
                    stock="gear",
                    duration_minutes=45,
                    description=(
                        "The central parking lot: equipment check, trip briefing, "
                        "and the guide's read on the mountain's weather."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="11:00",
                    title="Drive up to Prionia (1,100 m)",
                    node_type=NodeType.drive,
                    stock="drive",
                    duration_minutes=30,
                    description="Twenty winding minutes to the trailhead.",
                ),
                CornerstoneBeat(
                    hhmm="11:30",
                    title="Forest ascent to Spilios Agapitos (2,100 m)",
                    stock="forest",
                    duration_minutes=210,
                    description=(
                        "The E4 trail through shady forest and towering Bosnian "
                        "pines — 5.5 km and a thousand metres up over 3–3.5 hours."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="18:00",
                    title="Refuge evening — warm meal & early night",
                    node_type=NodeType.meal,
                    stock="refuge",
                    duration_minutes=150,
                    description=("A warm meal at the hut, kit laid out for the alpine start."),
                ),
            ),
        ),
        CornerstoneDay(
            day=2,
            title="Summit Day",
            hours=7.0,
            lat=40.08108,
            lng=22.35256,
            location_label="Mytikas summit",
            description=(
                "We start before dawn with headlamps to catch sunrise on the way "
                "up. The E4 trail leads out of the forest into the alpine zone; "
                "after about two hours we reach Skala peak (2,866 m) and put on "
                "helmets and harnesses. Following the Kakoskala ridge we scramble, "
                "roped to the guide, to the summit of Mytikas (2,918 m) — the "
                "highest point in Greece. After photos and rest we descend to the "
                "refuge for a light lunch, then continue down to Prionia and drive "
                "back to Litochoro. Around 1,000 m of gain and loss, ~6 hours."
            ),
            beats=(
                CornerstoneBeat(
                    hhmm="05:30",
                    title="Headlamp start — sunrise on the trail",
                    stock="headlamp",
                    duration_minutes=120,
                    description=(
                        "Out of the forest and into the alpine zone before dawn, "
                        "sunrise breaking on the way up."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="07:30",
                    title="Skala peak (2,866 m) — helmets & harnesses",
                    stock="scramble",
                    duration_minutes=90,
                    description="Gear on at the shoulder of the summit ridge.",
                ),
                CornerstoneBeat(
                    hhmm="09:00",
                    title="Kakoskala ridge to Mytikas (2,918 m)",
                    stock="scramble",
                    duration_minutes=90,
                    description=(
                        "Roped to the guide along the ridge scramble to the summit "
                        "of Mytikas — the highest point in Greece."
                    ),
                ),
                CornerstoneBeat(
                    hhmm="10:30",
                    title="Descend to the refuge — light lunch",
                    stock="refuge",
                    duration_minutes=180,
                    description="Photos, rest, then back down to Spilios Agapitos.",
                ),
                CornerstoneBeat(
                    hhmm="13:30",
                    title="Down to Prionia & drive to Litochoro",
                    stock="sunset",
                    duration_minutes=180,
                    description=(
                        "The last of ~1,000 m of descent, then the drive back to the village."
                    ),
                ),
            ),
        ),
    ),
)


def cornerstone_for_nights(nights: int, *, longest: int) -> OlympusCornerstone:
    """Pick the cornerstone for a spine of ``nights`` length.

    The longest supported spine anchors on the full *Path to Symbolism* ascent;
    every shorter spine anchors on the *Guided Olympus Summit — 2 Days* push.
    """
    return SYMBOLISM if nights >= longest else GUIDED_2DAY


__all__ = [
    "BEAT_STOCK",
    "GUIDED_2DAY",
    "SYMBOLISM",
    "CornerstoneBeat",
    "CornerstoneDay",
    "OlympusCornerstone",
    "cornerstone_for_nights",
]
