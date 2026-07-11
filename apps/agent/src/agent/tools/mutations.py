"""Mutation tools — update node status, reschedule a node (move), set trip timing."""

from __future__ import annotations

from typing import Any, Literal

from strands import tool

from agent.backend import BackendError, get_json, patch_json, pin_ctx


@tool
async def update_node_status(
    node_id: str,
    status: Literal["pending", "approved", "booked", "confirmed", "discarded"],
) -> dict:
    """Flip a node's status — approve, discard, or revert to pending.

    Use this in planning mode when the advisor directs a change
    ("drop the modern hotel", "approve the Bernina Express") or when
    the client is resolving an ``alternative_to`` cluster.

    If the itinerary is locked by the advisor, the API returns a
    ``locked`` outcome — surface that to the user ("the advisor is
    editing right now; try again in a moment") rather than retrying.

    If the node is already approved, booked, or confirmed, the API
    refuses the change with a ``status_locked`` reason (the node also
    carries a ``lock_reason`` you can read on the graph). That's not a
    retryable error — explain it conversationally and offer to involve an
    advisor ("that hotel is already booked; I'd need an advisor to move
    it") rather than trying again.

    Returns the updated node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return await patch_json(
        f"/itinerary/{itinerary_id}/nodes/{node_id}",
        json={"status": status},
    )


@tool
async def update_node_details(
    node_id: str,
    title: str | None = None,
    description: str | None = None,
    cost_amount: str | None = None,
    cost_currency: str | None = None,
    cost_kind: Literal["per_person", "total"] | None = None,
    confirmation_number: str | None = None,
) -> dict:
    """Edit a card's own fields — rename it, set or correct its price, write a
    description, or record a supplier confirmation number.

    This edits the card's substance; it does NOT approve, discard, or
    reschedule (``update_node_status`` and ``move_node`` do those). Pass only
    the fields you're changing:

    - ``title`` — rename the card.
    - ``description`` — the card's descriptive text, shown on its detail view.
    - ``cost_amount`` + ``cost_currency`` — the card's price. Both are required
      together (``"400.00"`` + ``"USD"``); pass ``cost_kind`` to say whether
      the amount is ``per_person`` or a single ``total`` (it defaults to
      whatever the card already carries). This is how a pasted-link card
      finally gets a price.
    - ``confirmation_number`` — the supplier's booking reference / PNR, for
      something the advisor booked manually outside our inventory.

    If the itinerary is locked by the advisor, the API returns ``locked`` —
    surface it, don't retry. A card that is already approved, booked, or
    confirmed refuses field edits: a non-staff session gets ``status_locked``
    (explain that firmed cards need an advisor), and an advisor session gets
    ``demote_before_edit`` (offer to demote the card with ``update_node_status``
    first, then re-apply the edit, then restore the status — and only do that
    dance when the advisor confirms).

    Returns the updated node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")

    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if cost_amount is not None or cost_currency is not None or cost_kind is not None:
        # The API's cost columns are both-or-neither; refuse a half pair here
        # so the model gets a clear reason instead of a 400.
        if not cost_amount or not cost_currency:
            raise BackendError(status=None, reason="cost_pair_required")
        body["cost_amount"] = cost_amount
        body["cost_currency"] = cost_currency
        if cost_kind is not None:
            body["cost_kind"] = cost_kind

    if description is not None or confirmation_number is not None:
        # The PATCH replaces metadata wholesale (same constraint move_node
        # handles), so read the node's current metadata and merge — otherwise
        # we'd wipe its snapshot / start_time / duration.
        graph = await get_json(f"/itinerary/{itinerary_id}")
        nodes = (graph or {}).get("nodes", [])
        current = next((n for n in nodes if str(n.get("id")) == str(node_id)), None)
        if current is None:
            raise BackendError(status=None, reason="not_found")
        metadata: dict[str, Any] = dict(current.get("metadata") or {})
        if description is not None:
            metadata["description"] = description
        if confirmation_number is not None:
            metadata["confirmation_number"] = confirmation_number
        body["metadata"] = metadata

    if not body:
        raise BackendError(status=None, reason="nothing_to_update")

    return await patch_json(
        f"/itinerary/{itinerary_id}/nodes/{node_id}",
        json=body,
    )


@tool
async def move_node(node_id: str, starts_at: str) -> dict:
    """Reschedule a node to a new start time — the timeline equivalent of a drag.

    ``starts_at`` is an ISO-8601 datetime WITH offset (e.g.
    ``"2025-07-02T20:00:00+09:00"``); keep the node's own timezone, and the day
    is taken from the date you pass. Use this to reshape an alternative version
    the traveler is working on, or to move a still-editable card on a draft.

    On the agreed plan an already approved/booked node is locked — the API
    refuses with ``status_locked``. Don't retry: branch an alternative version
    (``fork_itinerary``) and move it there. Requires an itinerary pinned to the
    session. Returns the updated node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")

    # The PATCH replaces metadata wholesale, so read the node's current metadata
    # and merge the new start_time in — otherwise we'd wipe its snapshot / cost /
    # duration. The backend keeps a free-standing note's starts_at column in sync
    # with metadata.start_time on its side.
    graph = await get_json(f"/itinerary/{itinerary_id}")
    nodes = (graph or {}).get("nodes", [])
    current = next((n for n in nodes if str(n.get("id")) == str(node_id)), None)
    if current is None:
        raise BackendError(status=None, reason="not_found")
    metadata: dict[str, Any] = dict(current.get("metadata") or {})
    metadata["start_time"] = starts_at

    return await patch_json(
        f"/itinerary/{itinerary_id}/nodes/{node_id}",
        json={"metadata": metadata},
    )


@tool
async def update_trip_details(
    title: str | None = None,
    brief: str | None = None,
) -> dict:
    """Name the adventure and/or capture its brief — the trip's own identity.

    Use this the moment the trip's direction is clear enough to deserve a
    name: ``title`` is the short evocative name the traveler will see
    everywhere ("Dolomites by First Light"), and ``brief`` is the trip's goal
    in a sentence, in the traveler's own terms ("A week of via ferrata with
    my brother, somewhere quiet"). Pass only what you're setting — an omitted
    field is left untouched. Refine either as the picture sharpens; this is
    an edit, not a one-shot.

    This edits the trip itself (not a card). Requires an itinerary pinned to
    the session. Returns the updated itinerary; the entrypoint observes the
    result and yields an ``itinerary_updated`` frame so the surface showing
    the trip's details refreshes.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")

    body: dict[str, Any] = {}
    if title is not None and title.strip():
        body["title"] = title.strip()
    if brief is not None and brief.strip():
        body["brief"] = brief.strip()
    if not body:
        raise BackendError(status=None, reason="nothing_to_update")

    return await patch_json(f"/itinerary/{itinerary_id}", json=body)


@tool
async def update_trip_timing(
    timing_kind: Literal["exact", "window", "flexible"],
    date_start: str | None = None,
    date_end: str | None = None,
    duration_nights: int | None = None,
    timing_note: str | None = None,
) -> dict:
    """Set the trip's dates once they're known — the timing at the trip level.

    Use this the moment the traveler settles the *when*: a vague brief like
    "sometime in August 2026" becomes concrete dates, or a fixed window
    loosens back to flexible. This edits the trip itself (not a card), so the
    whole itinerary re-renders around the new dates.

    ``timing_kind`` picks how to read the fields, and you must pass what that
    kind needs:
    - ``exact`` — the trip is booked to specific days. Pass ``date_start`` and
      ``date_end`` (both ISO dates, ``"YYYY-MM-DD"``).
    - ``window`` — dates are still soft but bounded. Pass ``date_start`` and
      ``date_end`` for the acceptable window, plus ``duration_nights`` for the
      target length inside it ("~7 nights within Jun–Aug").
    - ``flexible`` — no dates chosen yet. Pass only ``timing_kind``; any stored
      dates are cleared. Use this when the traveler steps back from a date they
      had picked.

    ``timing_note`` is optional free text for constraints the dates can't hold
    ("not during school term", "back by a Sunday"); omit it to leave the stored
    note untouched.

    Requires an itinerary pinned to the session. Returns the updated itinerary.
    The entrypoint observes this result and yields an ``itinerary_updated``
    frame so the timeline refreshes around the new dates.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")

    # The PATCH is partial (exclude_unset on the API side) and treats an
    # explicit null as "clear". Build the body per timing_kind so we only ever
    # clear dates on a deliberate switch to ``flexible`` — never by accident.
    body: dict[str, Any] = {"timing_kind": timing_kind}
    if timing_kind == "flexible":
        body["date_start"] = None
        body["date_end"] = None
        body["duration_nights"] = None
    else:
        # exact + window both carry a range. Refuse a dateless call rather than
        # wiping the stored dates — a missing date here is a model slip, not an
        # intent to clear.
        if not date_start or not date_end:
            raise BackendError(status=None, reason="dates_required")
        body["date_start"] = date_start
        body["date_end"] = date_end
        if duration_nights is not None:
            body["duration_nights"] = duration_nights
    if timing_note is not None:
        body["timing_note"] = timing_note

    return await patch_json(f"/itinerary/{itinerary_id}", json=body)
