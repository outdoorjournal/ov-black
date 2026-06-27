"""Fork tool — branch the current itinerary into an alternative version (G2/G3).

A fork is a versioned clone: a fresh itinerary carrying a deep copy of this one's
nodes/edges, editable independently of the live plan. Pre-booked nodes copy in
editable; already-booked/confirmed nodes carry over LOCKED (you can't fork away a
paid booking). Staff later diff the fork against the baseline and reconcile the
changes they accept (G3).

After forking, the session **re-pins to the alternative** (G3, §4.1) so the agent's
subsequent mutations target the fork, not the agreed plan: a DB re-pin (POST
/sessions, idempotent per (client_id, audience)) for future turns, plus an
in-process ``pin_ctx`` set so even a fork-then-edit within the same turn lands on
the alternative.
"""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from agent.backend import BackendError, pin_ctx, post_json

logger = logging.getLogger("agent.tools.fork")


async def _repin_session_to_fork(pin: dict[str, Any], fork_id: str) -> None:
    """Re-pin the session to the fork — DB (future turns) + in-process (this turn).

    Best-effort: the fork already succeeded, so a re-pin failure must not fail the
    tool. The DB re-pin reuses the idempotent ``POST /sessions`` reuse path, which
    updates ``agent_sessions.itinerary_id`` for the matching (client_id, audience).
    """
    client_id = pin.get("client_id")
    audience = pin.get("audience", "traveler")
    if client_id:
        try:
            await post_json(
                "/sessions",
                json={
                    "client_id": client_id,
                    "itinerary_id": fork_id,
                    "audience": audience,
                },
            )
        except BackendError as exc:
            logger.warning("fork.repin_failed", extra={"reason": exc.reason})
    # In-process re-pin so a fork-then-mutate within THIS turn hits the alternative.
    pin_ctx.set({**pin, "itinerary_id": fork_id})


@tool
async def fork_itinerary(title: str | None = None) -> dict:
    """Create an alternative version (a fork) of the current itinerary.

    Use this when the traveler wants to explore a different shape for the trip
    without disturbing the agreed plan ("what if we did Kyoto instead of Osaka?",
    "show me a slower version"). The fork is a full, independent copy they can
    rework; anything already booked carries over locked, and staff reconcile the
    changes back in later.

    After this call the session is **on the alternative version** — your further
    edits (status changes, new cards) apply to it, not the agreed plan. Always
    speak of it as "an alternative version", never a "fork". You cannot merge it
    yourself; the traveler can ask staff to, via ``request_reconcile``.

    Args:
        title: Optional name for the fork. Defaults to ``"{baseline} (fork)"``.

    Requires an itinerary pinned to the session. Returns the fork's graph — its
    ``itinerary.id`` is the new fork, ``itinerary.forked_from_id`` points back at
    the baseline, and every node carries ``forked_from_node_id`` lineage plus a
    ``lock_reason`` on any carried-over booked node.
    """
    pin = pin_ctx.get() or {}
    itinerary_id = pin.get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="no_itinerary_pinned")
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    graph = await post_json(f"/itinerary/{itinerary_id}/fork", json=body)
    fork_id = (graph or {}).get("itinerary", {}).get("id")
    if fork_id:
        await _repin_session_to_fork(pin, str(fork_id))
    return graph
