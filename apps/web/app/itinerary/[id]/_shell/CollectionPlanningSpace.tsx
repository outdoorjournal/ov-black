"use client";

// The Collection destination (M006/PS1) — the wish list as its own routed
// surface. It reads the same graph store (unscheduled, non-discarded nodes), so
// it is a view over the spine, never a parallel store. Browse-only for now; the
// DndContext is a harmless anchor so cards don't warn out of a provider and so
// PS5's pick-then-place has somewhere to hang. Scheduling from here (the
// cross-surface place-mode overlay) lands in PS5.

import { DndContext } from "@dnd-kit/core";

import { CollectionRail } from "@/app/_components/itinerary-graph/collection/CollectionRail";

export function CollectionPlanningSpace() {
  return (
    // A flex row so the board (w-full, no flex-1 of its own) stretches to fill
    // the height via the default cross-axis stretch — matching how the timeline
    // renders the dominant board today.
    <div className="flex min-h-0 flex-1">
      <DndContext>
        <CollectionRail variant="board" />
      </DndContext>
    </div>
  );
}
