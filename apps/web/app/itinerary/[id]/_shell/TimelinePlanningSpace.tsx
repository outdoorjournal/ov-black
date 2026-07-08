"use client";

// The Timeline destination (M006/PS1). Today's timeline, unchanged — just moved
// inside the shell: the responsive md/mobile split the retired ItineraryGraphView
// used to own, minus the concierge (now the shell's people axis). The chat aside
// and the mobile peek-sheet are suppressed here; the shell hosts the concierge.

import { useEffect } from "react";

import { HorizontalView } from "@/app/_components/itinerary-graph/views/horizontal/HorizontalView";
import { MobileItineraryLayout } from "@/app/_components/itinerary-graph/views/mobile/MobileItineraryLayout";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import { CollectionOverlay } from "./CollectionOverlay";
import { useOpenNode } from "./useOpenNode";

export function TimelinePlanningSpace() {
  // A card click routes to the full-bleed card detail (PS4) rather than the old
  // in-place modal — same target on both breakpoints, so a deep-link resolves.
  const openNode = useOpenNode();
  // ADV-15: load the per-card billing chips so the board shows how each card
  // relates to the invoices (a no-op for travelers / without credentials).
  const storeApi = itineraryGraphStore.useStoreApi();
  useEffect(() => {
    storeApi.getState().refreshBilling();
  }, [storeApi]);
  return (
    <>
      {/* md+ : the horizontal timeline canvas. */}
      <div className="hidden md:contents">
        <HorizontalView embedded showConciergeAside={false} onOpenNode={openNode} />
      </div>
      {/* below md : the swipe-driven day pager of the same graph. */}
      <div className="contents md:hidden">
        <MobileItineraryLayout embedded showConciergeSheet={false} onOpenNode={openNode} />
      </div>
      {/* The Collection as a summonable layer for pick-then-place (md–xl band,
          where it isn't already a rail beside the timeline). */}
      <CollectionOverlay />
    </>
  );
}
