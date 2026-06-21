"""Per-depth Analyze runners (TravelGraph Phase 5 / B5).

Each runner exposes ``async def run(session, *, itinerary_id, scope) -> RunOutput``
and is dispatched by :mod:`app.services.analyze` based on the run's depth.
Shared types + graph-loading + geometry helpers live in :mod:`.common`;
``standard`` composes on top of ``shallow``.
"""
