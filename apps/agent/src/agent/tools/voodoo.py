"""``get_voodoo_doll`` — read the calling client's own Voodoo Doll."""

from __future__ import annotations

from strands import tool

from agent.backend import get_json


@tool
async def get_voodoo_doll() -> dict:
    """Fetch the calling client's Voodoo Doll.

    Returns the full typed core + JSONB long-tail: passions, motivations,
    travel history, triggers, constraints, deal-breakers, dream-trip
    signals, OSINT notes, contact preference, group type, and estimated
    net worth. Use this as ground truth when deciding what to propose or
    how to frame a reply — the doll has been seeded by an advisor and
    may already cover most of what you need to know about the client.

    Does not mutate any state. Safe to call any time.
    """
    return await get_json("/me/voodoo-doll")
