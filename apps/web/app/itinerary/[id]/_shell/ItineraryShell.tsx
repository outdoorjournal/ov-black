"use client";

// The planner shell (M006/PS1). This is the ONE client boundary the routed
// itinerary lives inside: it owns the graph store Provider + the server-fresh
// timeline context, and lays out the two axes around the routed planning space —
//   places (the Rail)  ·  people (the ConciergeColumn)  ·  the view (children).
//
// Why the shell (not the view) owns the Provider: the layout persists across
// navigation between the routed destinations (timeline / collection / studio),
// so the store — and the open concierge — survive a view switch instead of
// unmounting with the page. The `key={itineraryId}` in the layout gives each
// trip its own fresh store; sibling-route nav keeps the same instance.
//
// First-run intake still gates ahead of everything: a trip with no brief shows
// the intake and mounts neither the store nor the concierge until a goal exists
// (mirrors the retired ItineraryBuilderScreen).

import { useState } from "react";

import type { ItineraryStatus } from "@ov-black/api-client";

import { ItineraryIntake } from "@/app/_components/itinerary-graph/intake/ItineraryIntake";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/horizontalTypes";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import type { UserRole } from "@/lib/role";

import { ConciergeColumn } from "./ConciergeColumn";
import { ConciergeControlProvider } from "./ConciergeControl";
import { MobileTabBar } from "./MobileTabBar";
import { PlaceModeLayer } from "./PlaceModeLayer";
import { Rail } from "./Rail";

export type ItineraryShellProps = {
  timeline: ItineraryTimeline;
  baselineTitle: string | null;
  itineraryId: string;
  status: ItineraryStatus;
  role: UserRole;
  apiBaseUrl: string | null;
  accessToken: string | null;
  viewerOpenForkId: string | null;
  /** True when the trip has no brief yet — gate on the first-run intake. */
  needsBrief: boolean;
  audience: "advisor" | "traveler";
  /** The active routed destination (timeline / collection / studio / …). */
  children: React.ReactNode;
};

export function ItineraryShell({
  timeline,
  baselineTitle,
  itineraryId,
  status,
  role,
  apiBaseUrl,
  accessToken,
  viewerOpenForkId,
  needsBrief,
  audience,
  children,
}: ItineraryShellProps) {
  const [showIntake, setShowIntake] = useState(needsBrief);
  // <1100px the concierge is a summonable overlay (opened from the Rail on a
  // tablet, or the Chat tab on a phone); ≥1100px it is an in-flow column and
  // this flag is inert. Q5 default — full collapse polish lands in PS6.
  const [conciergeOpen, setConciergeOpen] = useState(false);

  if (showIntake && apiBaseUrl && accessToken) {
    return (
      <ItineraryIntake
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        audience={audience}
        onSaved={() => setShowIntake(false)}
        onSkip={() => setShowIntake(false)}
      />
    );
  }

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
      }}
    >
      <TimelineDataProvider value={{ timeline, baselineTitle }}>
        <ConciergeControlProvider
          value={{ openConcierge: () => setConciergeOpen(true) }}
        >
          <div
            data-testid="itinerary-shell"
            className="relative flex min-h-0 flex-1 overflow-hidden"
          >
            <Rail onOpenConcierge={() => setConciergeOpen(true)} />

            {/* People axis. ≥1100px: an in-flow column. Below that: hidden until
                summoned, then a full-screen overlay (neutralised back to in-flow
                at ≥1100 so the state never traps the desktop layout). */}
            <aside
              data-testid="concierge-column"
              className={
                "flex-col bg-paper " +
                "min-[1100px]:flex min-[1100px]:w-[380px] min-[1100px]:shrink-0 min-[1100px]:border-r min-[1100px]:border-ink/10 " +
                (conciergeOpen
                  ? "fixed inset-0 z-40 flex min-[1100px]:static min-[1100px]:inset-auto min-[1100px]:z-auto"
                  : "hidden min-[1100px]:flex")
              }
            >
              <ConciergeColumn onClose={() => setConciergeOpen(false)} />
            </aside>

            {/* Planning space — the routed destination fills the rest. The
                padding clears the fixed mobile tab bar (h-14); none on md+. */}
            <main
              data-testid="planning-space"
              className="relative flex min-w-0 flex-1 flex-col pb-14 md:pb-0"
            >
              {children}
            </main>

            <MobileTabBar onOpenConcierge={() => setConciergeOpen(true)} />

            {/* Place mode's cross-surface chrome (PS5): the holding chip + undo
                toast float above every destination, driven by the shared store. */}
            <PlaceModeLayer />
          </div>
        </ConciergeControlProvider>
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}
