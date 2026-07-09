// Shared advisor-facing copy for booking error tokens (M005/I3 + supplier
// booking). The service returns a stable `detail` token on a 4xx/409; this maps
// each to a human sentence. Kept in its own module so BookingPanel and the
// supplier slot-picker dialog share one source of truth without a circular
// import.

export const ERROR_COPY: Record<string, string> = {
  not_found: "That item could not be found.",
  advisor_only: "Booking is advisor-only.",
  forbidden: "You don't have access to book here.",
  node_not_paid: "Can't book yet — no covering paid invoice line. Pay it first, or override.",
  dates_not_pinned: "Booking needs real dates — pin the trip's dates first.",
  booked_dates_locked:
    "Booked items are committed to these dates — cancel the bookings before moving or loosening them.",
  already_booked: "That item is already booked.",
  node_not_approved: "Only an approved item can be booked.",
  node_not_booked: "Only a booked item can be confirmed.",
  no_booking: "No booking found for that item.",
  offer_required: "Re-price the flight first to hold a fresh fare.",
  offer_expired: "The held fare lapsed — re-price before booking.",
  offer_unavailable: "The held fare is gone; re-search the flight.",
  reprice_failed: "Couldn't re-price with the supplier. Try again.",
  node_has_no_cost: "That item has no cost to book against.",
  supplier_ref_required: "Enter a supplier confirmation #.",
  already_cancelled: "That booking is already cancelled.",
  refund_declined: "The refund was declined — nothing was changed. Resolve it with the processor.",
  refund_gateway_unavailable: "Couldn't reach the payment processor. Nothing changed — try again.",
  payments_unconfigured: "Payments aren't configured, so the refund can't be processed.",
  // Real supplier booking (Bokun).
  supplier_selection_required: "Pick an availability slot before booking.",
  supplier_reserve_failed: "Couldn't hold that slot with the supplier. Try another, or refresh.",
  supplier_confirm_failed: "The supplier declined to confirm the hold. Nothing was booked.",
  supplier_cancel_failed: "Couldn't cancel with the supplier — nothing was refunded. Try again.",
  supplier_provider_unavailable: "This booking's supplier isn't reachable right now.",
  supplier_availability_failed: "Couldn't load availability from the supplier. Try again.",
  node_not_supplier_bookable: "This item isn't set up for live supplier booking.",
  network_error: "Could not reach the server. Try again in a moment.",
};

export function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}
