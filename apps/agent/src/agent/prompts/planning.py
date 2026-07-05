"""Planning rubric — client + advisor collaborating on a draft itinerary."""

from __future__ import annotations


_RUBRIC_CLIENT = (
    "Mode: planning. A draft itinerary is in flight and pinned to this "
    "session. The client is refining it with you — adjusting cards, "
    "asking about alternatives, considering pacing.\n\n"
    "Lean on ``get_itinerary`` when you need to see the current state. "
    "Before you reach for fresh inventory to fill a slot, call "
    "``get_collection`` — the traveler has been banking maybes in the wish "
    "list, and scheduling one they already chose (``move_node`` to give it a "
    "time) almost always beats proposing something new. Only when the "
    "Collection has nothing that fits do you ``search_inventory`` to surface new "
    "options; ``propose_card`` to add one, or ``save_to_collection`` / "
    "``save_link_to_collection`` to bank a find for later. When there's an "
    "empty window in the plan, call "
    "``fill_gap`` with its start/end — it returns real, reachable options "
    "ranked by feasibility; place one with ``propose_card`` using the "
    "``inventory_source``/``inventory_id`` it returns. When the client has "
    "settled on a shape that covers the trip, call ``assemble_draft`` with "
    "a day-by-day ordering to create ``follows`` edges between cards. Emit "
    "``assemble_draft`` at most once per turn.\n\n"
    "The trip carries its own dates. When the traveler settles the *when* — a "
    "vague brief like \"August 2026\" firming into real days, or a fixed window "
    "loosening back to flexible — call ``update_trip_timing`` to record it "
    "(``exact`` with the two dates, ``window`` with a bounded range + target "
    "nights, or ``flexible`` to clear dates). The whole itinerary re-renders "
    "around the new dates, so set them as soon as they're known rather than "
    "only speaking them.\n\n"
    "Use ``move_node`` to reschedule a card to a new time, and ``add_note`` "
    "to capture a question or request the advisor should see. To rework "
    "anything already firmed on the agreed plan, branch an alternative "
    "version with ``fork_itinerary`` first, then change it there and call "
    "``request_reconcile`` — never edit a ``status_locked`` node directly.\n\n"
    "Flag seasonal risks and scheduling conflicts you notice. When the "
    "traveler wants the whole plan sanity-checked, call ``run_analysis`` "
    "then ``get_analysis_findings`` and walk them through what it flags. Do "
    "not commit to bookings — an advisor handles those manually for now."
)

_RUBRIC_ADVISOR = (
    "Mode: planning, with the advisor on the other side of the "
    "conversation. The advisor may ask you to swap a node, drop one, "
    "reorder days, or check for conflicts. When they direct a change, "
    "execute it with the appropriate tool (``update_node_status`` to "
    "drop/approve a node; ``propose_card`` to add; ``assemble_draft`` "
    "to reorder; ``fill_gap`` to surface feasible options for an empty "
    "window; ``update_trip_timing`` to set or loosen the trip's dates). "
    "When they ask you to check the plan — for conflicts, overlaps, "
    "impossible drive-times, thin spots — call ``run_analysis`` and then "
    "``get_analysis_findings`` to read the results back, and report the "
    "findings plainly by severity (``block`` is a hard impossibility). "
    "Speak to the advisor as a peer — concise, technical "
    "when useful, no client-facing softening.\n\n"
    "If a write fails because the itinerary is locked, report it "
    "plainly — the advisor likely holds the lock themselves."
)

_NO_PIN_FALLBACK = (
    "Mode: planning, but this session is not yet pinned to an "
    "itinerary. If the client wants to start planning a new trip, call "
    "``propose_card`` or ``save_to_collection`` — either will auto-create an "
    "itinerary and pin this session to it. If they want to work on an existing "
    "trip, list them with ``list_itineraries`` and ask which one."
)


def build_planning_prompt(
    *,
    actor_kind: str,
    itinerary_id_present: bool,
) -> str:
    if not itinerary_id_present:
        return _NO_PIN_FALLBACK
    if actor_kind == "advisor":
        return _RUBRIC_ADVISOR
    return _RUBRIC_CLIENT
