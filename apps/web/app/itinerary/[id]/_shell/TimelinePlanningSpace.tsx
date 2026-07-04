"use client";

// The Timeline destination (M006/PS1). Today's timeline, unchanged — just moved
// inside the shell: the responsive md/mobile split the retired ItineraryGraphView
// used to own, minus the concierge (now the shell's people axis). The chat aside
// and the mobile peek-sheet are suppressed here; the shell hosts the concierge.

import { HorizontalView } from "@/app/_components/itinerary-graph/views/horizontal/HorizontalView";
import { MobileItineraryLayout } from "@/app/_components/itinerary-graph/views/mobile/MobileItineraryLayout";

export function TimelinePlanningSpace() {
  return (
    <>
      {/* md+ : the horizontal timeline canvas. */}
      <div className="hidden md:contents">
        <HorizontalView embedded showConciergeAside={false} />
      </div>
      {/* below md : the swipe-driven day pager of the same graph. */}
      <div className="contents md:hidden">
        <MobileItineraryLayout embedded showConciergeSheet={false} />
      </div>
    </>
  );
}
