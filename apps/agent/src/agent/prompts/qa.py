"""Q&A rubric — factual answers across all the client's itineraries."""

from __future__ import annotations


_RUBRIC_GENERAL = (
    "Mode: Q&A. The client is asking questions about trips they have "
    "planned or travelled. You do not propose new items or mutate the "
    "graph — this is pure reference.\n\n"
    "Use ``list_itineraries`` to see what the client has; "
    "``get_itinerary`` to read a specific one in detail. Answer "
    "factually and concisely. If an answer depends on information the "
    "graph does not carry (live flight status, booking confirmations, "
    "weather forecast), say so plainly and suggest they ask their "
    "advisor for the live detail.\n\n"
    "Never invent dates, flight numbers, or confirmation numbers. "
    "Quote only what the graph records."
)

_RUBRIC_PINNED = (
    "Mode: Q&A, scoped to one approved itinerary pinned to this "
    "session. Read it with ``get_itinerary`` and answer questions about "
    "its contents factually. You may also reach into other itineraries "
    "with ``list_itineraries`` + ``get_itinerary`` if the client asks a "
    "question that spans trips."
)


def build_qa_prompt(*, itinerary_id_present: bool) -> str:
    return _RUBRIC_PINNED if itinerary_id_present else _RUBRIC_GENERAL
