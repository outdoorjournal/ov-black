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

from dataclasses import dataclass
from typing import Any


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
