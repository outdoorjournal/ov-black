"""Presentation surfaces — the drawer beside the correspondence.

These tools don't mutate the itinerary graph; they *present*. Each returns a
``{surface_id, kind, payload}`` dict that :mod:`agent.translate` shapes into a
``surface`` SSE frame, and the browser slides the payload out as a rich panel
next to the chat (a route mini-brochure, a decision between alternatives).

Two kinds so far:

- ``present_route`` — verifiable geometry (polyline, distances, durations)
  comes from the backend's ``POST /agent/route`` (Google Routes, key stays
  server-side); the agent supplies only the narrative ``headline`` and
  ``highlights``.
- ``present_options`` — fully agent-authored. The traveler's pick returns as
  their next chat message, so the tool result reminds the model to expect it.

Validation is enforced here (like ``propose_timeline``) because payloads are
rendered to the traveler verbatim: malformed shapes reject as tool errors
rather than reaching the browser.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError
from strands import tool

from agent.backend import BackendError, agent_post_json
from agent.schemas import PresentOptionsArgs, PresentRouteArgs


def _surface_id() -> str:
    return f"srf-{uuid.uuid4().hex[:12]}"


@tool
async def present_route(
    origin: str,
    destination: str,
    mode: str = "drive",
    waypoints: list[str] | None = None,
    headline: str = "",
    highlights: list[dict] | None = None,
) -> dict:
    """Slide out a route mini-brochure showing how to get from A to B.

    Use this when the traveler asks (or you want to show) how a journey
    works — the panel renders the real route on a map with distance and
    travel time, plus your notes underneath. Compute happens on a live
    routing engine, so the numbers are trustworthy; you supply the story.

    - ``origin`` / ``destination`` — loose place strings ("Tokyo Station",
      "Hakone"), the same names you'd use in prose.
    - ``mode`` — ``drive`` (default), ``walk``, ``bicycle`` or ``transit``.
    - ``waypoints`` — up to 5 intermediate stops, in order.
    - ``headline`` — one short line above the map ("The coast road south").
    - ``highlights`` — up to 5 ``{"title", "detail"}`` notes rendered under
      the map: why this routing, a stop worth making, what to expect.

    Keep narrating in prose — one line to introduce the brochure is enough;
    the panel carries the detail. Returns ``{"surface_id", "kind", "payload"}``
    on success, or ``{"error": "<reason>"}`` (e.g. ``route_not_found`` when the
    pair isn't routable in that mode — consider another mode, or say so).
    """
    try:
        args = PresentRouteArgs.model_validate(
            {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "waypoints": waypoints or [],
                "headline": headline,
                "highlights": highlights or [],
            }
        )
    except ValidationError:
        return {"error": "invalid_route_args"}

    try:
        plan = await agent_post_json(
            "/agent/route",
            json={
                "origin": args.origin,
                "destination": args.destination,
                "waypoints": args.waypoints,
                "mode": args.mode,
            },
        )
    except BackendError as exc:
        return {"error": exc.reason}
    if not isinstance(plan, dict):
        return {"error": "route_upstream_error"}

    payload: dict = {"route": plan}
    if args.headline:
        payload["headline"] = args.headline
    if args.highlights:
        payload["highlights"] = [
            {"title": h.title, **({"detail": h.detail} if h.detail else {})}
            for h in args.highlights
        ]
    return {"surface_id": _surface_id(), "kind": "route", "payload": payload}


@tool
async def present_options(
    question: str,
    options: list[dict],
    context: str = "",
) -> dict:
    """Lay a decision before the traveler as tappable option cards.

    Use this instead of prose when you're genuinely asking the traveler to
    choose between 2–4 alternatives — the panel gives each option room for
    your case, and the traveler answers by tapping one. Their pick arrives
    as their next message (e.g. "I'd like to go with \"…\"."); act on it then.

    Each option is a small object::

        {"title": "Ryokan Sasayuri-an", "tagline": "three rooms, cedar bath",
         "case": "Why this one fits…", "node_id": "<uuid, optional>"}

    - ``title`` — the option's name (required, what the pick echoes back).
    - ``tagline`` — one short qualifying line.
    - ``case`` — your case for it: a sentence or three, concrete over florid.
    - ``node_id`` — when the option corresponds to a card you already
      proposed, pass its node id so the panel can link them.

    Pass ``question`` (the decision itself) and optional ``context`` (one
    line of framing shown above the cards). Present at most one decision per
    turn, and don't restate every option in prose — introduce the choice,
    then let the panel carry it. Returns the validated surface, or
    ``{"error": "invalid_options"}`` if the shape is malformed.
    """
    try:
        args = PresentOptionsArgs.model_validate(
            {"question": question, "options": options, "context": context}
        )
    except ValidationError:
        return {"error": "invalid_options"}

    shaped = []
    for i, opt in enumerate(args.options):
        entry: dict = {
            "id": opt.id or f"opt-{i + 1}",
            "title": opt.title,
        }
        if opt.tagline:
            entry["tagline"] = opt.tagline
        if opt.case:
            entry["case"] = opt.case
        if opt.node_id:
            entry["node_id"] = opt.node_id
        shaped.append(entry)

    payload: dict = {"question": args.question, "options": shaped}
    if args.context:
        payload["context"] = args.context
    return {"surface_id": _surface_id(), "kind": "options", "payload": payload}
