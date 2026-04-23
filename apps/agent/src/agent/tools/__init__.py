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
from agent.tools.proposals import assemble_draft, propose_card
from agent.tools.voodoo import get_voodoo_doll


_TOOLS_ONBOARDING = [
    get_voodoo_doll,
    search_inventory,
    get_inventory_detail,
    propose_card,
]

_TOOLS_PLANNING = [
    get_voodoo_doll,
    get_itinerary,
    list_alternatives,
    search_inventory,
    get_inventory_detail,
    propose_card,
    assemble_draft,
    update_node_status,
]

_TOOLS_QA = [
    get_voodoo_doll,
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
