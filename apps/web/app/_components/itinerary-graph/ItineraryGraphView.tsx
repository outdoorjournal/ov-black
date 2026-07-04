"use client";

// Top-level entry for rendering an itinerary graph. This is the public surface
// the rest of the app imports — every consumer (the traveler route, the staff
// route, the prototype sandbox) renders THIS, never a specific view directly.
//
// Responsibilities:
//   1. Own the view-agnostic store Provider, seeded with the domain + the
//      viewer's role + their credentials. One store instance is shared by
//      whichever layout is active.
//   2. Decide the layout responsively, in-place (no route change, no reload):
//        - md and up → the selected desktop view (horizontal today; a
//          "vertical"/"calendar" view drops in here later with no store change).
//        - below md → a swipe-driven mobile layout of the SAME store.
//      Both are rendered under the one Provider and toggled with `display`
//      utilities, so resizing the viewport flips between them seamlessly.
//
// Capability: the viewer's `role` is resolved on the server and passed straight
// through; `canEdit` is derived from it inside the store. Each viewer is handed
// their OWN Supabase token (already in their browser session), so the
// credentials are non-null for travelers too — that is what powers the
// traveler-facing concierge. The backend's advisor guards remain the real
// authority over any mutation.

import type { ItineraryStatus } from "@ov-black/api-client";

import type { UserRole } from "@/lib/role";

import type { ItineraryTimeline } from "./model/types";
import { itineraryGraphStore } from "./store/itineraryGraphStore";
import { TimelineDataProvider } from "./TimelineDataContext";
import { HorizontalView } from "./views/horizontal/HorizontalView";
import { MobileItineraryLayout } from "./views/mobile/MobileItineraryLayout";

export type ItineraryGraphViewKind = "horizontal";

export type ItineraryGraphViewProps = {
  timeline: ItineraryTimeline;
  itineraryId: string;
  status: ItineraryStatus;
  /** Server-resolved viewer role; the store derives `canEdit` from it. */
  role: UserRole;
  /** The viewer's own API credentials (their Supabase session token). */
  apiBaseUrl?: string | null;
  accessToken?: string | null;
  /** Demo-only: start already locked so the API-less sandbox can edit. */
  startLocked?: boolean;
  /** Which desktop view to render at md+. Defaults to the horizontal timeline. */
  view?: ItineraryGraphViewKind;
  /** Title of the baseline this itinerary forked from (G3), for the banner. */
  baselineTitle?: string | null;
  /** The viewer's own open fork of this baseline ("My version"), if any, so the
   *  two-version toggle resolves to it instead of spawning a duplicate. */
  viewerOpenForkId?: string | null;
  /** When true the view fills its flex parent (`flex-1 min-h-0`) instead of the
   *  viewport (`h-screen`), so it can sit BELOW the shared AppHeader. Standalone
   *  usages (the prototype sandbox) leave it false to own the full viewport. */
  embedded?: boolean;
};

export function ItineraryGraphView({
  timeline,
  itineraryId,
  status,
  role,
  apiBaseUrl = null,
  accessToken = null,
  startLocked = false,
  view = "horizontal",
  baselineTitle = null,
  viewerOpenForkId = null,
  embedded = false,
}: ItineraryGraphViewProps) {
  return (
    <itineraryGraphStore.Provider
      initial={{
        timeline,
        itineraryId,
        status,
        role,
        apiBaseUrl,
        accessToken,
        viewerOpenForkId,
        startLocked,
      }}
    >
      {/* The server-fresh timeline (day scaffold + timing) flows through context
          so both layouts read it without prop-drilling and it refreshes on
          `router.refresh()`; the store above holds the mutable graph domain. */}
      <TimelineDataProvider value={{ timeline, baselineTitle }}>
        {/* md+ : the selected desktop view. `display: contents` so the view's
            own full-viewport root behaves as a direct child of the Provider. */}
        <div className="hidden md:contents">
          {view === "horizontal" ? <HorizontalView embedded={embedded} /> : null}
        </div>
        {/* below md : the swipe-driven mobile layout of the same graph. */}
        <div className="contents md:hidden">
          <MobileItineraryLayout embedded={embedded} />
        </div>
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}
