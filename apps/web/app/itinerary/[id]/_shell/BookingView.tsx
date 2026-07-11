"use client";

// The Booking destination — the advisor's book/confirm/cancel cockpit for this
// trip as a first-class Rail surface, rehomed from the old dashboard footer.
// Booking is advisor-only server-side and independent of the graph edit-lock (it
// must work on an approved, build-frozen trip), so it gates on ROLE (`canManage`),
// not `selectEditable`; a traveler who reaches it sees it read-only.

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import { BookingPanel } from "@/app/_components/itinerary-graph/views/horizontal/BookingPanel";

export function BookingView() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  if (!itineraryId) {
    return (
      <p className="mx-auto max-w-3xl px-4 py-10 font-sans text-sm text-ink/50">
        Loading…
      </p>
    );
  }

  return (
    <div
      data-testid="booking-view"
      className="min-h-0 flex-1 overflow-y-auto bg-paper"
    >
      <div className="mx-auto w-full max-w-3xl px-4 py-6">
        <BookingPanel
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
          canManage={role === "advisor"}
        />
      </div>
    </div>
  );
}
