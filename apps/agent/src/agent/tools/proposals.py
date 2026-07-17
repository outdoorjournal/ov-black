"""Write tools that add to the itinerary graph.

These are the tools whose results the entrypoint translates into SSE
frames for the browser — ``propose_card`` fires a ``card_proposed``
frame, ``assemble_draft`` fires ``draft_assembled``. The tool itself
hits the existing FastAPI write routes with the forwarded JWT; the API
is the single source of truth for every write.
"""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from agent.backend import BackendError, delete_json, get_json, pin_ctx, post_json

logger = logging.getLogger(__name__)


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
        "status": "pending",
        "title": title or (snapshot or {}).get("title") or "",
        "source": source,
        "source_id": source_id,
        "metadata": {"snapshot": snapshot or {}},
    }
    return await post_json(
        f"/itinerary/{itinerary_id}/nodes", json=payload
    )


@tool
async def propose_flight(source: str, source_id: str) -> dict:
    """Add a flight (or other inventory item) to the itinerary as a typed card.

    Use this instead of ``propose_card`` for results that carry rich
    structured detail — flights especially. The ``source``/``source_id``
    pair must come from a prior ``search_inventory`` result (e.g.
    ``source='duffel'``). The backend re-fetches the item and derives the
    card metadata server-side — for a flight that means cabin, seat, and
    depart/arrive times land on the node automatically; for a Duffel offer
    the re-fetch also refreshes the (time-boxed) quote.

    Like ``propose_card``, this auto-creates and pins a draft itinerary if
    the session has none. Returns the persisted node; the entrypoint yields
    a ``card_proposed`` frame to the UI.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")

    if itinerary_id is None:
        created = await post_json("/itinerary", json={"title": "Concierge draft"})
        itinerary_id = created.get("id")
        if not itinerary_id:
            raise BackendError(status=None, reason="itinerary_create_failed")
        pin_ctx.set({**pin, "itinerary_id": itinerary_id})

    result = await post_json(
        f"/itinerary/{itinerary_id}/nodes/from-inventory",
        json={"source": source, "source_id": source_id},
    )
    await _guard_flight_timing(itinerary_id, result)
    return result


def _created_node_ids(result: dict) -> set[str]:
    """Every node id this write persisted — the primary plus any siblings.

    A round-trip Duffel offer lands as an outbound + return pair carried on
    ``additional_nodes``; both must roll back together if either leg is
    infeasible.
    """
    ids: set[str] = set()
    primary = result.get("id")
    if isinstance(primary, str):
        ids.add(primary)
    for extra in result.get("additional_nodes") or []:
        extra_id = (extra or {}).get("id")
        if isinstance(extra_id, str):
            ids.add(extra_id)
    return ids


def _is_flight(result: dict) -> bool:
    if result.get("type") == "flight":
        return True
    return any((extra or {}).get("type") == "flight" for extra in result.get("additional_nodes") or [])


def _blocking_flight_findings(graph: dict, created: set[str]) -> list[str]:
    """Messages of block-severity flight findings that touch the created nodes.

    Phase 5 (doc/itin-time.md): the graph read carries the KERNEL's
    feasibility findings — the same engine the advisor UI renders — so the
    guard consults them instead of re-deriving flight timing agent-side.
    """
    messages: list[str] = []
    for finding in graph.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if finding.get("severity") != "block":
            continue
        if not str(finding.get("code") or "").startswith("flight"):
            continue
        node_ids = {str(nid) for nid in finding.get("node_ids") or []}
        if node_ids & created:
            messages.append(str(finding.get("message") or "flight infeasible"))
    return messages


async def _guard_flight_timing(itinerary_id: str, result: dict) -> None:
    """Reject a flight that can't physically make the plan, and roll it back.

    A prose rule already told the model to land before the first item; it once
    narrated its way past it and booked an arrival a day late (a flight in the
    middle of day 1). This is the hard floor: after the write, re-read the
    graph and, if the kernel's feasibility findings block the just-placed leg
    (arrives after the first commitment / departs before the last one ends),
    delete it and raise so the model must choose a feasible offer instead.
    The analysis itself runs in the API's kernel (one feasibility engine for
    agent, API, and UI); this guard only reacts to it. Fail-open on any guard
    error — a guard bug must never swallow a real proposal.
    """
    if not _is_flight(result):
        return
    created = _created_node_ids(result)
    if not created:
        return
    try:
        graph = await get_json(f"/itinerary/{itinerary_id}")
        blocking = _blocking_flight_findings(graph, created)
    except Exception:  # noqa: BLE001 — guard must not mask a successful write
        logger.warning("propose_flight.timing_guard_failed", exc_info=True)
        return
    if not blocking:
        return
    for node_id in created:
        try:
            await delete_json(f"/itinerary/{itinerary_id}/nodes/{node_id}")
        except BackendError:
            logger.warning("propose_flight.rollback_failed", extra={"node_id": node_id})
    raise BackendError(
        status=None,
        reason="flight_schedule_conflict: " + " ".join(blocking),
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
