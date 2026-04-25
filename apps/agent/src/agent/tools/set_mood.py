"""``set_mood`` — instruct the basecamp ambience to shift palette + imagery.

The agent calls this when the conversation drifts toward a place or vibe
that has a curated mood in :mod:`agent.moods`. Returning the chosen
``mood_id`` lets ``translate_event`` surface a ``mood`` SSE frame the
front-end consumes; ``AtmosFrame`` reads the id and crossfades.

Validation is intentionally strict: an unknown id rejects the call
rather than falling back, so a typo from the model surfaces as a tool
error in the trace instead of silently dropping the ambience shift.
"""

from __future__ import annotations

from typing import get_args

from strands import tool

from agent.moods import MOOD_DESCRIPTIONS, MoodId


_VALID_MOOD_IDS: frozenset[str] = frozenset(get_args(MoodId))


@tool
async def set_mood(mood_id: str) -> dict:
    """Shift the basecamp ambience to the named mood.

    Pass one of the curated mood ids from your system prompt (e.g.
    ``paris-cafe`` when the client mentions Paris, ``kyoto-zen`` for
    Japan, ``alpine`` for mountains). Call at most once per turn, and
    only when the client has said something specific enough that a
    palette shift would feel responsive — not on generic openings.

    Returns ``{"mood_id": "<id>"}`` on success or
    ``{"error": "unknown_mood", "mood_id": "<id>"}`` on a typo.
    """
    if mood_id not in _VALID_MOOD_IDS:
        return {"error": "unknown_mood", "mood_id": mood_id}
    return {"mood_id": mood_id, "description": MOOD_DESCRIPTIONS[mood_id]}
