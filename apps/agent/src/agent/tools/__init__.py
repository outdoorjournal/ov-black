"""Per-mode tool bundles for the Strands ``Agent`` factory.

Each tool is decorated with ``strands.tool``. Bundling by mode means the
agent sees only the tools that make sense for its persona — the Q&A
agent cannot propose cards, the onboarding agent cannot update node
status. The lists below are the single source of truth; modes.py reads
them to instantiate each turn's ``Agent``.
"""

from __future__ import annotations

from agent.schemas import Mode
from agent.tools.fill import fill_gap
from agent.tools.fork import fork_itinerary
from agent.tools.inventory import get_inventory_detail, search_inventory
from agent.tools.itinerary import get_itinerary, list_alternatives, list_itineraries
from agent.tools.mutations import move_node, update_node_status, update_trip_timing
from agent.tools.notes import add_note
from agent.tools.proposals import assemble_draft, propose_card, propose_flight
from agent.tools.reconcile import reconcile_alternative
from agent.tools.request_reconcile import request_reconcile
from agent.tools.set_mood import set_mood
from agent.tools.timeline import propose_timeline
from agent.tools.traveler import (
    get_traveler_context,
    record_dossier_inference,
    record_party_member,
    record_profile_fact,
)


_TOOLS_ONBOARDING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    record_party_member,
    search_inventory,
    get_inventory_detail,
    propose_card,
    propose_timeline,
    set_mood,
]

_TOOLS_PLANNING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    record_party_member,
    get_itinerary,
    list_alternatives,
    search_inventory,
    get_inventory_detail,
    fill_gap,
    propose_card,
    propose_flight,
    propose_timeline,
    assemble_draft,
    update_node_status,
    update_trip_timing,
    move_node,
    add_note,
    fork_itinerary,
    request_reconcile,
    reconcile_alternative,
    set_mood,
]

# Q&A is read-mostly: the traveler is asking, not building. They may still leave
# a note (feedback for staff) or branch + reshape an alternative version — so the
# write surface here is deliberately narrow (add_note / fork / move /
# request_reconcile), never the full authoring toolkit.
_TOOLS_QA = [
    get_traveler_context,
    list_itineraries,
    get_itinerary,
    propose_timeline,
    add_note,
    fork_itinerary,
    move_node,
    request_reconcile,
]


def tools_for(mode: Mode) -> list:
    if mode is Mode.onboarding:
        return list(_TOOLS_ONBOARDING)
    if mode is Mode.planning:
        return list(_TOOLS_PLANNING)
    return list(_TOOLS_QA)


__all__ = ["tools_for"]
