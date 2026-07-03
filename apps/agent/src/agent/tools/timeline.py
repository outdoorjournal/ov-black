"""``propose_timeline`` — render a vertical "shape of the trip" block.

When the agent wants to lay out a sequence of days — the rough shape of a
week, the arc of a route — prose turns into a wall of text. This tool lets it
emit that shape as a structured block instead. The runtime materialises the
validated result as a fenced ``ov-timeline`` markdown block inside the reply
(see :mod:`agent.translate`), which the web client swaps for a real timeline
component. Because the block lives in the message body, it orders itself against
the surrounding prose and survives a page reload with no extra persistence.

Validation is enforced here (not just documented) because the output is
rendered to the traveler verbatim: a malformed shape rejects with an error the
translator drops, rather than surfacing broken markup.
"""

from __future__ import annotations

from pydantic import ValidationError
from strands import tool

from agent.schemas import ProposeTimelineArgs


@tool
async def propose_timeline(days: list[dict], caption: str = "") -> dict:
    """Lay out a sequence of days as a vertical timeline in your reply.

    Use this instead of writing the day-by-day shape out in prose. Each day is
    a small object::

        {"label": "Day 1", "title": "Arrive Fiskardo", "detail": "embark, settle"}

    - ``label`` — the left-rail marker, e.g. ``"Day 1"`` or ``"Days 2–3"``.
    - ``title`` — the anchor of the day: a place or a move (``"North toward
      Lefkada"``).
    - ``detail`` — optional supporting line (``"overnight at Nidri or Sivota"``).

    Pass an optional ``caption`` (e.g. ``"The shape of the week"``) shown above
    the timeline. Provide 2–30 days.

    Emit at most one timeline per turn, and keep a line of prose around it —
    introduce the shape before, and offer the next step after. Do NOT also
    describe the days in prose; the block renders them.

    Returns the validated ``{"caption", "days"}`` on success, or
    ``{"error": "invalid_timeline"}`` if the shape is malformed (the block is
    then dropped rather than rendered broken).
    """
    try:
        args = ProposeTimelineArgs.model_validate({"days": days, "caption": caption})
    except ValidationError:
        return {"error": "invalid_timeline"}

    cleaned = [
        {
            "label": day.label,
            "title": day.title,
            **({"detail": day.detail} if day.detail else {}),
        }
        for day in args.days
    ]
    result: dict = {"days": cleaned}
    if args.caption:
        result["caption"] = args.caption
    return result
