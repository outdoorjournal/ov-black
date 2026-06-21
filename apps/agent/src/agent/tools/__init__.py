"""Per-mode tool bundles for the Strands ``Agent`` factory.

Each tool is decorated with ``strands.tool``. Bundling by mode means the
agent sees only the tools that make sense for its persona — the Q&A
agent cannot propose cards, the onboarding agent cannot update node
status. The lists below are the single source of truth; modes.py reads
them to instantiate each turn's ``Agent``.
"""

from __future__ import annotations

from agent.schemas import Mode
from agent.tools.inventory import get_inventory_detail, search_inventory
from agent.tools.itinerary import get_itinerary, list_alternatives, list_itineraries
from agent.tools.mutations import update_node_status
from agent.tools.proposals import assemble_draft, propose_card, propose_flight
from agent.tools.set_mood import set_mood
from agent.tools.traveler import (
    get_traveler_context,
    record_dossier_inference,
    record_profile_fact,
)


_TOOLS_ONBOARDING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    search_inventory,
    get_inventory_detail,
    propose_card,
    set_mood,
]

_TOOLS_PLANNING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    get_itinerary,
    list_alternatives,
    search_inventory,
    get_inventory_detail,
    propose_card,
    propose_flight,
    assemble_draft,
    update_node_status,
    set_mood,
]

# Q&A is read-only — no fact recording, the traveler is asking, not telling.
_TOOLS_QA = [
    get_traveler_context,
    list_itineraries,
    get_itinerary,
]


def tools_for(mode: Mode) -> list:
    if mode is Mode.onboarding:
        return list(_TOOLS_ONBOARDING)
    if mode is Mode.planning:
        return list(_TOOLS_PLANNING)
    return list(_TOOLS_QA)


__all__ = ["tools_for"]
