"use client";

// Top-level entry for rendering an itinerary graph. This is the public surface
// the rest of the app imports — every consumer (the traveler route, the staff
// route, the prototype sandbox) renders THIS, never a specific view directly.
//
// Responsibilities:
//   1. Own the view-agnostic store Provider, seeded with the domain + the
//      staff-editing config (canEdit + credentials). One store instance is
//      shared by whichever view is active.
//   2. Pick the active view. Today there is only "horizontal"; a "calendar"
//      view would drop in as another case here with zero changes to the store,
//      the adapter, or the route.
//
// Security: `canEdit` is resolved on the server (advisor vs. traveler).
// Travelers get canEdit=false and null credentials, so no token reaches the
// browser and the editing actions are inert; the backend's advisor guards are
// the real authority.

import type { ItineraryStatus } from "@ov-black/api-client";

import type { ItineraryTimeline } from "./model/types";
import { itineraryGraphStore } from "./store/itineraryGraphStore";
import { HorizontalView } from "./views/horizontal/HorizontalView";

export type ItineraryGraphViewKind = "horizontal";

export type ItineraryGraphViewProps = {
  timeline: ItineraryTimeline;
  itineraryId: string;
  status: ItineraryStatus;
  /** Server-resolved: advisor → true, traveler → false. */
  canEdit: boolean;
  /** Only passed for staff; null for travelers so no credential leaks. */
  apiBaseUrl?: string | null;
  accessToken?: string | null;
  /** Demo-only: start already locked so the API-less sandbox can edit. */
  startLocked?: boolean;
  /** Which view to render. Defaults to the horizontal timeline. */
  view?: ItineraryGraphViewKind;
  /** Title of the baseline this itinerary forked from (G3), for the banner. */
  baselineTitle?: string | null;
};

export function ItineraryGraphView({
  timeline,
  itineraryId,
  status,
  canEdit,
  apiBaseUrl = null,
  accessToken = null,
  startLocked = false,
  view = "horizontal",
  baselineTitle = null,
}: ItineraryGraphViewProps) {
  return (
    <itineraryGraphStore.Provider
      initial={{
        timeline,
        itineraryId,
        status,
        canEdit,
        apiBaseUrl,
        accessToken,
        startLocked,
      }}
    >
      {view === "horizontal" ? (
        <HorizontalView timeline={timeline} baselineTitle={baselineTitle} />
      ) : null}
    </itineraryGraphStore.Provider>
  );
}
