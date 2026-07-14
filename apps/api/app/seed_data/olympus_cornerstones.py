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

from app.inventory.schemas import ItineraryDay


@dataclass(frozen=True)
class CornerstoneDay:
    """One day of a cornerstone trip's internal itinerary.

    Baked from the OV trip's ``itineraries[].days[]`` (``GET /api/trips/{id}``),
    the same source the live from-inventory path reads. These become the summit
    node's subgraph children so the anchor card reads as the real multi-day OV
    adventure it is — an expandable day-by-day journey, not a single photo card.
    """

    #: 1-based day index within the trip.
    day: int
    title: str
    #: Active hours on the trail, when the vendor states them (OV ``hours``).
    hours: float | None = None
    #: Plain-text day description (vendor HTML stripped at authoring time).
    description: str | None = None


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
    #: The trip's internal day-by-day itinerary — baked from OV, materialized as
    #: the summit node's subgraph children (see :func:`itinerary_days`).
    days: tuple[CornerstoneDay, ...] = field(default_factory=tuple)

    def itinerary_days(self) -> list[ItineraryDay]:
        """The cornerstone's days as :class:`ItineraryDay`, subgraph-ready.

        Same shape the OV provider emits from a live detail fetch, so the
        template builder can feed these through the shared subgraph-metadata
        builder and the children render identically to an inventory-born
        multi-day card. No per-day geo (OV doesn't expose it here), so
        ``location`` is left unset.
        """
        return [
            ItineraryDay(
                day=d.day,
                title=d.title,
                description=d.description,
                hours=d.hours,
                location=None,
            )
            for d in self.days
        ]

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
        }


#: id_hint of the fixture node the cornerstone enriches — the Mytikas summit,
#: the pinnacle experience present in every spine (5/7/14 all include day 4).
CORNERSTONE_ANCHOR_ID_HINT = "d04-summit"


_OV_CDN = "https://cdn-pub.prod.outdoorvoyage.com"


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
            title="Pick up from Thessaloniki airport",
            description=(
                "Pick up from Thessaloniki airport and transfer to your hotel in "
                "Litochoro village just in time for dinner. Dinner and overnight "
                "in Litochoro."
            ),
        ),
        CornerstoneDay(
            day=2,
            title="National Park museum and Enipeas River",
            description=(
                "We visit the National Park museum for a virtual ascent from the "
                "foothills to the top of the mountain, learning the history, flora, "
                "and fauna of Olympus. We find the place where the cause of the "
                "Trojan war began, hear local myths and tales, and — for the brave "
                "— swim in the crystal-clear, freezing waters of the Enipeas river. "
                "The day ends at the old monastery of Saint Dionysios and the cave "
                "where he lived as a hermit. Dinner and overnight in Litochoro."
            ),
        ),
        CornerstoneDay(
            day=3,
            title="Apostolidis refuge",
            description=(
                "Our goal is the Muses Plateau. We pass the Ithakisios cave, where "
                "the great painter lived for more than 15 years, and the old "
                "shepherds' settlement. After a light lunch at Petrostrouga refuge "
                "we climb three more hours to the Muses Plateau, standing at last "
                "before the Throne of Zeus. Dinner and overnight in Apostolidis "
                "Refuge."
            ),
        ),
        CornerstoneDay(
            day=4,
            title="Mytikas summit & Petrostrouga Refuge",
            description=(
                "Today we climb to the Mytikas summit, for those who want and can. "
                "The whole group can visit Profitis Ilias summit and its chapel — "
                "the highest in the Balkans. After some free time we begin the "
                "descent before sunset to Petrostrouga Refuge. Dinner and overnight "
                "in Petrostrouga Refuge."
            ),
        ),
        CornerstoneDay(
            day=5,
            title="Vergina and Aridea",
            description=(
                "We wake to coffee on the finest balcony of Mount Olympus, with "
                "panoramic views over the Thermaikos gulf and the Pieria Riviera. "
                "From Gortsia we head to Vergina and the royal tomb of Philip II — "
                "father of Alexander the Great — and close the day soaking in an "
                "outdoor hot bath in the Aridaia region. Dinner and overnight in a "
                "guesthouse."
            ),
        ),
        CornerstoneDay(
            day=6,
            title="Thessaloniki Airport",
            description=(
                "Depending on your departure time we adapt the schedule (a final "
                "visit and so on) and then take you back to Thessaloniki Airport."
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
    days=(
        CornerstoneDay(
            day=1,
            title="Litochoro – Prionia – Spilios Agapitos Hut",
            hours=4.0,
            description=(
                "We meet around 10:00 at Litochoro's central parking lot for an "
                "equipment check and briefing, then drive to the Prionia trailhead "
                "(1,100 m). From there we hike the most popular path on Olympus — "
                "part of the E4 European trail — climbing steadily through shady "
                "forest and towering Bosnian pines to the Spilios Agapitos refuge "
                "(2,100 m): about 5.5 km and +1,000 m over roughly 3–3.5 hours. At "
                "the hut we enjoy a warm meal, rest, and prepare for summit day."
            ),
        ),
        CornerstoneDay(
            day=2,
            title="Summit Day",
            hours=7.0,
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
    "CORNERSTONE_ANCHOR_ID_HINT",
    "GUIDED_2DAY",
    "SYMBOLISM",
    "OlympusCornerstone",
    "cornerstone_for_nights",
]
