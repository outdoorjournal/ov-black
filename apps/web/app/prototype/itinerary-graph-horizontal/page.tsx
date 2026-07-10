import { ItineraryGraphView } from "@/app/_components/itinerary-graph/ItineraryGraphView";

import { getHorizontalTimeline } from "./_fixtures";

export const metadata = {
  title: "Itinerary graph · horizontal · OV Black prototype",
  description:
    "Design sandbox #3 for the OV Black itinerary: per-day columns, shared minute-of-day y axis, drag-and-drop between days, new card design language.",
};

export default function ItineraryGraphHorizontalPrototypePage() {
  const timeline = getHorizontalTimeline();
  // Sandbox: advisor role + startLocked so the drag/edit affordances are
  // exercisable without an API to acquire a real lock against. No credentials →
  // mutations are local-only (no network).
  return (
    <ItineraryGraphView
      timeline={timeline}
      itineraryId={timeline.itinerary.id}
      status="in_studio"
      role="advisor"
      startLocked
    />
  );
}
