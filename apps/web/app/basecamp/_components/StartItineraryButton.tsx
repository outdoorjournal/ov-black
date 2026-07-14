// Traveler self-serve entry point: create a trip and land in the builder's
// first-run intake. Lives with the "Your itineraries" surface (the atelier
// section + its empty state) rather than the masthead. A server-action form so
// the create + redirect happen on one response with the caller's session.

import { startNewItinerary } from "@/app/_actions/start-itinerary";

export function StartItineraryButton() {
  return (
    <form action={startNewItinerary}>
      <button
        type="submit"
        className="rounded-md bg-brand px-4 py-1.5 text-[11px] uppercase tracking-label text-brand-foreground transition-colors hover:bg-brand/90"
      >
        Start a new itinerary
      </button>
    </form>
  );
}
