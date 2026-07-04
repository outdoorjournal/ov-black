"use client";

// The server-fresh slice of an itinerary, held in context so every planning
// surface can read it WITHOUT taking it as a prop.
//
// Why a context and not the store: the graph *domain* (nodes / edges / edits)
// lives in `itineraryGraphStore`, seeded once and preserved across a
// `router.refresh()` so in-session work survives. But the day scaffold + timing
// window are rendered server-side onto the `timeline` prop and must REFRESH when
// the trip's dates change (the concierge's `onItineraryUpdated` fires
// `router.refresh()`, which re-runs the route's RSC with a fresh `timeline`).
// If a view read `timeline` from the store it would go stale on refresh, so the
// fresh server value flows through this context instead — re-rendered on every
// refresh, while the store keeps the mutable domain. Both the routed shell
// (ItineraryShell) and the standalone entry (ItineraryGraphView) provide it, so
// consumers (HorizontalView, MobileItineraryLayout, …) never see the difference.

import { createContext, useContext, type ReactNode } from "react";

import type { ItineraryTimeline } from "./model/horizontalTypes";

export type TimelineData = {
  /** The server-rendered timeline (day scaffold + timing) — fresh on refresh. */
  timeline: ItineraryTimeline;
  /** Title of the baseline this itinerary forked from (G3), for the banner. */
  baselineTitle: string | null;
};

const TimelineDataContext = createContext<TimelineData | null>(null);
TimelineDataContext.displayName = "TimelineDataContext";

export function TimelineDataProvider({
  value,
  children,
}: {
  value: TimelineData;
  children: ReactNode;
}): ReactNode {
  return (
    <TimelineDataContext.Provider value={value}>
      {children}
    </TimelineDataContext.Provider>
  );
}

export function useTimelineData(): TimelineData {
  const value = useContext(TimelineDataContext);
  if (!value) {
    throw new Error(
      "useTimelineData called outside of <TimelineDataProvider>. Wrap the planning surface in the itinerary shell (or ItineraryGraphView).",
    );
  }
  return value;
}
