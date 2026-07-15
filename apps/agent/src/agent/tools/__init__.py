"""Per-mode tool bundles for the Strands ``Agent`` factory.

Each tool is decorated with ``strands.tool``. Bundling by mode means the
agent sees only the tools that make sense for its persona — the Q&A
agent cannot propose cards, the onboarding agent cannot update node
status. The lists below are the single source of truth; modes.py reads
them to instantiate each turn's ``Agent``.
"""

from __future__ import annotations

from agent.schemas import Mode
from agent.tools.analyze import get_analysis_findings, run_analysis
from agent.tools.campaign import assemble_campaign_spine
from agent.tools.collection import (
    add_collection_note,
    get_collection,
    save_link_to_collection,
    save_to_collection,
)
from agent.tools.fill import fill_gap
from agent.tools.fork import fork_itinerary
from agent.tools.intake import complete_intake
from agent.tools.inventory import get_inventory_detail, search_inventory
from agent.tools.itinerary import get_itinerary, list_alternatives, list_itineraries
from agent.tools.money import get_billing_state, get_booking_state
from agent.tools.mutations import (
    move_node,
    update_node_details,
    update_node_status,
    update_trip_details,
    update_trip_timing,
)
from agent.tools.notes import add_note
from agent.tools.proposals import assemble_draft, propose_card, propose_flight
from agent.tools.reading import suggest_reading
from agent.tools.reconcile import reconcile_alternative
from agent.tools.request_reconcile import request_reconcile
from agent.tools.set_mood import set_mood
from agent.tools.surfaces import present_options, present_route
from agent.tools.thread import post_thread_message
from agent.tools.timeline import propose_timeline
from agent.tools.transfer import add_transfer
from agent.tools.traveler import (
    add_trip_traveler,
    get_traveler_context,
    record_dossier_inference,
    record_party_member,
    record_profile_fact,
    record_travel_logistics,
    remove_trip_traveler,
    update_party_member,
)


_TOOLS_ONBOARDING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    record_travel_logistics,
    record_party_member,
    update_party_member,
    add_trip_traveler,
    remove_trip_traveler,
    search_inventory,
    get_inventory_detail,
    propose_card,
    # Collection (wish list) — the dominant surface before a timeline exists.
    save_to_collection,
    save_link_to_collection,
    add_collection_note,
    get_collection,
    propose_timeline,
    # Drawer surfaces — a route brochure or a laid-out decision beside the chat.
    present_route,
    present_options,
    # Editorial reading suggestions from the owned properties (basecamp-only).
    suggest_reading,
    set_mood,
]

# Intake (the immersive first conversation on a brand-new trip) is gathering,
# never building: trip identity + timing + party + private facts + ambience,
# plus the hand-off signal. Deliberately NO search/propose/collection tools —
# the rubric promises "we'll shape the trip together right after this".
_TOOLS_INTAKE = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    record_travel_logistics,
    record_party_member,
    update_party_member,
    add_trip_traveler,
    remove_trip_traveler,
    update_trip_details,
    update_trip_timing,
    set_mood,
    complete_intake,
]

_TOOLS_PLANNING = [
    get_traveler_context,
    record_profile_fact,
    record_dossier_inference,
    record_travel_logistics,
    record_party_member,
    update_party_member,
    add_trip_traveler,
    remove_trip_traveler,
    get_itinerary,
    list_alternatives,
    search_inventory,
    get_inventory_detail,
    # Feasibility: check the plan for problems, then rank fixes for a gap.
    run_analysis,
    get_analysis_findings,
    fill_gap,
    propose_card,
    propose_flight,
    # Collection (wish list) — shop it before searching fresh inventory.
    save_to_collection,
    save_link_to_collection,
    add_collection_note,
    get_collection,
    propose_timeline,
    # Drawer surfaces — a route brochure or a laid-out decision beside the chat.
    present_route,
    present_options,
    # Real, tier-aware ground transfer (airport car, etc.) from a live route.
    add_transfer,
    # Campaign spine — lay down the length-snapped skeleton on a campaign trip.
    assemble_campaign_spine,
    assemble_draft,
    update_node_status,
    update_node_details,
    update_trip_details,
    update_trip_timing,
    move_node,
    add_note,
    fork_itinerary,
    request_reconcile,
    reconcile_alternative,
    set_mood,
    # Money awareness (AGT-3) — read-only; the agent narrates, staff execute.
    get_billing_state,
    get_booking_state,
    # Escalation to the human advisor thread (AGT-4).
    post_thread_message,
]

# Q&A is read-mostly: the traveler is asking, not building. They may still leave
# a note (feedback for staff) or branch + reshape an alternative version — so the
# write surface here is deliberately narrow (add_note / fork / move /
# request_reconcile), never the full authoring toolkit.
_TOOLS_QA = [
    get_traveler_context,
    list_itineraries,
    get_itinerary,
    get_collection,
    propose_timeline,
    # Drawer surfaces are read-only presentation — safe in Q&A ("how do we
    # get from the ryokan to the station?" earns a route brochure).
    present_route,
    present_options,
    # Reading suggestions — the tool self-gates to unpinned basecamp sessions,
    # so it's inert on a trip-pinned Q&A turn.
    suggest_reading,
    add_note,
    fork_itinerary,
    move_node,
    request_reconcile,
    # Money answers ("am I paid up?", "what's the confirmation #?") are
    # classic Q&A — both reads, never a money mutation (AGT-3).
    get_billing_state,
    get_booking_state,
    # Escalation to the human advisor thread (AGT-4).
    post_thread_message,
]


# Campaign kickoff is a PROSE-ONLY greeting: the spine + reading list are already
# on the canvas (seeded deterministically by /campaign/kickoff), so the model has
# nothing to build or read this turn. Handing it an empty toolset is the point —
# with no tools it cannot fire silent get_traveler_context / get_itinerary reads
# (each a round-trip + re-invocation + interleaved thinking) before the first
# token, which is what made the opener sit dark for a minute or two. The KICKOFF
# directive in the system prompt carries everything the greeting needs.
_TOOLS_KICKOFF: list = []


def tools_for(mode: Mode) -> list:
    if mode is Mode.onboarding:
        return list(_TOOLS_ONBOARDING)
    if mode is Mode.intake:
        return list(_TOOLS_INTAKE)
    if mode is Mode.planning:
        return list(_TOOLS_PLANNING)
    if mode is Mode.kickoff:
        return list(_TOOLS_KICKOFF)
    return list(_TOOLS_QA)


__all__ = ["tools_for"]
