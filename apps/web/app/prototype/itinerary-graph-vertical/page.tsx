import { VerticalShell } from "./_components/VerticalShell";
import { getVerticalTimeline } from "./_fixtures";

export const metadata = {
  title: "Itinerary graph · vertical · OV Black prototype",
  description:
    "Design sandbox #2 for the OV Black itinerary: vertical time axis, duration bars, ambient backdrop.",
};

export default function ItineraryGraphVerticalPrototypePage() {
  const timeline = getVerticalTimeline();
  return <VerticalShell timeline={timeline} />;
}
