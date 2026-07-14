"use client";

// The Reading destination — this trip's saved articles as their own routed
// surface. It reads the same graph store (article nodes only), so it is a view
// over the spine, never a parallel store. Articles used to sit inside the
// Collection; they now live here so the wish list stays places-to-do and the
// reading gets a magazine rack of its own.

import { useMemo } from "react";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { ReadingList } from "@/app/_components/reading/ReadingList";
import { isReadingArticle, toReadingItem } from "@/app/_components/reading/readingItem";

export function ReadingPlanningSpace() {
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const discardNode = itineraryGraphStore.useStore((s) => s.discardNode);
  const items = useMemo(
    () => nodes.filter(isReadingArticle).map(toReadingItem),
    [nodes],
  );

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {/* Remove = the store's soft-discard; the rack re-derives from the graph,
          so the tile disappears with the optimistic flip (and returns if the
          backend refuses). Per-trip items are underived, hence a single ref. */}
      <ReadingList items={items} onRemove={(item) => discardNode(item.id)} />
    </div>
  );
}
