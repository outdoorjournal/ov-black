"""Read-only money tools (AGT-3) — billing + booking state over the pinned plan.

The agent narrates and nudges; it NEVER moves money or books. Both tools are
pure reads over user-JWT routes (the same access gate as the traveler's own
invoice views), so the human-in-the-loop boundary stays structural: invoicing
executes in the advisor cockpit, booking through the money-gated booking flow.
"""

from __future__ import annotations

from strands import tool

from agent.backend import BackendError, get_json, pin_ctx


def _require_pinned_itinerary() -> str:
    itinerary_id = (pin_ctx.get() or {}).get("itinerary_id")
    if not itinerary_id:
        raise BackendError(status=None, reason="missing_itinerary_id")
    return str(itinerary_id)


@tool
async def get_billing_state() -> dict:
    """The pinned trip's money truth: trip total vs invoiced / paid /
    outstanding, plus what is still uninvoiced — per currency and per card.

    Use this whenever money comes up: "what do we owe?", "what's been billed?",
    "why can't this be booked yet?" (an unpaid card is the usual answer — the
    money gate refuses to book a node no paid invoice line covers), or when
    the live plan state shows an uninvoiced remainder worth flagging.

    Returns ``{rows, unbilled_nodes, invoices}``: ``rows`` is the per-currency
    reconciliation (``trip_total``, ``invoiced``, ``paid``, ``outstanding``,
    ``uninvoiced`` + count); ``unbilled_nodes`` lists each approved card whose
    effective cost isn't fully billed (``remaining`` is what a balance line
    would still charge); ``invoices`` gives each invoice's label, status,
    total, and paid amount.

    Read-only. You cannot create, issue, or pay an invoice — the advisor does
    that in their cockpit; offer to flag it to them instead.
    """
    itinerary_id = _require_pinned_itinerary()
    return await get_json(f"/itinerary/{itinerary_id}/billing")


@tool
async def get_booking_state() -> dict:
    """Where every bookable card stands: paid or not, booked, confirmed, and
    whether a held offer has gone stale.

    Use this for "is the hotel booked?", "what's our confirmation number?",
    "is that flight price still good?", or to warn that a held offer is about
    to expire. Covers the approved / booked / confirmed cards on the pinned
    itinerary.

    Returns ``{rows}``, one row per card: ``node_status``, the billed / paid /
    owed amounts (an approved card with ``paid_amount`` short of its cost
    cannot pass the money gate yet), ``booked_amount`` + ``supplier_ref`` +
    ``booked_at`` / ``confirmed_at`` once a booking exists, and the latest
    held offer's ``offer_amount`` / ``offer_expires_at`` / ``offer_expired``.

    Read-only. Booking and cancelling are advisor actions through the money
    gate — narrate the state and, if action is needed, flag it to the advisor.
    """
    itinerary_id = _require_pinned_itinerary()
    return await get_json(f"/itinerary/{itinerary_id}/booking-state")
