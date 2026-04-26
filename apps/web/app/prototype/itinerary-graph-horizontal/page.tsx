import { HorizontalShell } from "./_components/HorizontalShell";
import { getHorizontalTimeline } from "./_fixtures";

export const metadata = {
  title: "Itinerary graph · horizontal · OV Black prototype",
  description:
    "Design sandbox #3 for the OV Black itinerary: per-day columns, shared minute-of-day y axis, drag-and-drop between days, new card design language.",
};

export default function ItineraryGraphHorizontalPrototypePage() {
  const timeline = getHorizontalTimeline();
  return <HorizontalShell timeline={timeline} />;
}
