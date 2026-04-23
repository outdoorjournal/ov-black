"""Write tools that add to the itinerary graph.

These are the tools whose results the entrypoint translates into SSE
frames for the browser — ``propose_card`` fires a ``card_proposed``
frame, ``assemble_draft`` fires ``draft_assembled``. The tool itself
hits the existing FastAPI write routes with the forwarded JWT; the API
is the single source of truth for every write.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json


@tool
async def propose_card(
    source: str,
    source_id: str,
    title: str = "",
    snapshot: dict | None = None,
) -> dict:
    """Add one proposed-experience node to the client's itinerary.

    Use this when you want to put a real OV experience on the mood
    board. The ``source``/``source_id`` pair must come from a prior
    ``search_inventory`` result — never invent them. ``snapshot`` is
    the card the UI renders (title, cover_image, price, duration_days,
    difficulty, location, activities); it is stored verbatim in the
    node's metadata.

    If the session has an itinerary pinned, the node lands there.
    Otherwise, this call auto-creates a draft itinerary and pins the
    session to it — the next turn will be in planning mode.

    Returns the persisted node ``{id, type, status, title, source,
    source_id, metadata, ...}``. The entrypoint observes this result
    and yields a ``card_proposed`` frame to the UI.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")

    if itinerary_id is None:
        created = await post_json("/itinerary", json={"title": "Concierge draft"})
        itinerary_id = created.get("id")
        if not itinerary_id:
            raise BackendError(status=None, reason="itinerary_create_failed")
        # Pin the context so subsequent tool calls in this turn + the next
        # turn's detect-mode both see the new itinerary.
        pin_ctx.set({**pin, "itinerary_id": itinerary_id})

    payload: dict[str, Any] = {
        "type": "experience",
        "status": "proposed",
        "title": title or (snapshot or {}).get("title") or "",
        "source": source,
        "source_id": source_id,
        "metadata": {"snapshot": snapshot or {}},
    }
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes", json=payload
    )


@tool
async def assemble_draft(day_plan: list[dict]) -> dict:
    """Stitch proposed cards into a day-by-day sequence.

    Args:
        day_plan: List of ``{"day_index": int, "node_ids_in_order":
            [node_id, ...]}``. Reference only node ids surfaced on
            prior ``propose_card`` / ``get_itinerary`` calls.

    Creates ``follows`` edges between consecutive cards within each day
    and between the last node of one day and the first of the next.
    Returns ``{edges_created: int, edges: [...]}``.

    Call at most once per turn, and only in planning mode with the
    itinerary pinned. Emit a prose reply before or after — the UI renders
    a progress cue from the ``draft_assembled`` frame separately.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return await post_json(
        f"/itinerary/{itinerary_id}/assemble",
        json={"day_plan": day_plan},
    )
