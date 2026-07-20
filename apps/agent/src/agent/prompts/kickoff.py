"""Kickoff rubric — the campaign dashboard's opening prose greeting.

This is the first turn on a campaign trip. By the time it runs, the curated
spine (hotels, hikes, the summit) AND the reading list are ALREADY on the canvas
beside the traveler — the ``/campaign/kickoff`` endpoint laid them down
deterministically on arrival. So there is nothing to build or look up here.

The turn runs with NO tools on purpose (see ``_TOOLS_KICKOFF``): a prose-only
greeting streams its first token in a second or two, instead of sitting dark
while the model fires silent reads. The concrete beats of the greeting — which
shape to name, the reading-list chips, the gaps to ask about — arrive in the
``KICKOFF`` directive that FastAPI appends to the traveler context; this rubric
just sets the frame so the model writes prose and nothing else.
"""

from __future__ import annotations


_RUBRIC_KICKOFF = (
    "Mode: kickoff. This is the opening moment of a campaign trip. The curated "
    "shape is ALREADY on the canvas beside you — the spine of hotels, hikes, and "
    "the summit, plus a few reads dropped into the traveler's reading list. It is "
    "all in place; you are not building it and you have no tools this turn.\n\n"
    "Your whole job is to open the conversation in warm, tight PROSE and stop. "
    "Follow the KICKOFF directive already in your context: greet the shape you've "
    "laid out so it reads as intentional, mention the reads (echo the chips it "
    "gives you verbatim), and close on EXACTLY ONE question — the single most "
    "valuable thing the skeleton can't guess (who's coming, the way in, the "
    "dates), skipping anything the trip already carries: if the dates are "
    "pinned, don't ask about dates. One question means one — never a stack, and "
    "never an open-ended \"just say the word\". Do not narrate tools, plans, or "
    "scratchpad; the cards carry the detail, so keep it brief. The real work — "
    "searching a flight, sizing the ascent, seating the party — happens on the "
    "NEXT turns, once the traveler answers."
)


def build_kickoff_prompt() -> str:
    return _RUBRIC_KICKOFF
