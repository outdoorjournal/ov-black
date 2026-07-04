"use client";

// Navigate to a card's full-bleed detail (M006/PS4). Shared by every surface
// that renders cards — the timeline canvas, the mobile pager, the Collection —
// so a click means the same thing everywhere: open /itinerary/[id]/item/[nodeId].

import { useParams, useRouter } from "next/navigation";
import { useCallback } from "react";

export function useOpenNode(): (nodeId: string) => void {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const itineraryId = params.id;
  return useCallback(
    (nodeId: string) => {
      router.push(`/itinerary/${itineraryId}/item/${nodeId}`);
    },
    [router, itineraryId],
  );
}
