"""Curated mood palette the agent picks from when shifting basecamp ambience.

Mirrors the front-end ``MoodId`` union in ``apps/web/lib/atmos/moods.ts``.
The two lists must stay aligned — when adding a new mood, edit both. The
front-end is the source of truth for the actual palette/image; this list
is the source of truth for the *names the agent is allowed to emit*.

A `MoodId` Literal makes the runtime reject malformed agent calls early
instead of letting an invalid id reach the browser, where ``AtmosFrame``
would silently fall back to the default.
"""

from __future__ import annotations

from typing import Literal


MoodId = Literal[
    # Original 7 (shipped pre-basecamp; keyword-classified on /chat/{id})
    "glacial",
    "ember",
    "amber",
    "verdant",
    "tidal",
    "onyx",
    "alpine",
    # New basecamp additions — agent-driven only.
    "paris-cafe",
    "kyoto-zen",
    "savannah",
    "polar",
    "andes",
    "monsoon",
    "riviera",
    "highland",
]


# One-line palette descriptions the prompt enumerates so the agent picks
# semantically rather than by guessing from id strings alone.
MOOD_DESCRIPTIONS: dict[str, str] = {
    "glacial": "icy blues, austere — Iceland, Antarctica, glaciers, deep winter.",
    "ember": "warm reds and sand — Sahara, Morocco, desert, dusk fires.",
    "amber": "golden Tuscan light — vineyards, harvest, slow afternoons.",
    "verdant": "deep forest greens — jungle, rainforest, tropical canopy.",
    "tidal": "ocean teal and salt — coast, surf, archipelago, reefs.",
    "onyx": "near-black, candlelit — opera houses, hushed luxury, evening.",
    "alpine": "high-altitude granite + pine — mountains, lakes, brisk air.",
    "paris-cafe": "Parisian café tones — croissants, the Seine, bistro evenings.",
    "kyoto-zen": "Kyoto/Japan stillness — temples, ryokan, sakura, onsen.",
    "savannah": "East-African plains — safari, golden grass, big sky.",
    "polar": "aurora and snowfields — Lapland, Svalbard, husky-sled latitudes.",
    "andes": "high Andes earth — Machu Picchu, Atacama, Cusco terracotta.",
    "monsoon": "river-soft greens — Kerala, Halong Bay, Mekong, Vietnam rains.",
    "riviera": "Mediterranean blue — Amalfi, Capri, Positano, yacht decks.",
    "highland": "Scottish-isle greys and heather — fjords, lochs, stone cottages.",
}


def mood_palette_lines() -> str:
    """Return a newline-delimited 'id — description' table for prompt embed."""
    return "\n".join(f"- {mid} — {MOOD_DESCRIPTIONS[mid]}" for mid in MOOD_DESCRIPTIONS)
