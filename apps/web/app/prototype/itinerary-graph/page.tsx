import { PrototypeShell } from "./_components/PrototypeShell";
import { getSampleTimelines } from "./_fixtures";

export const metadata = {
  title: "Itinerary graph · OV Black prototype",
  description:
    "Design sandbox for the OV Black itinerary visualization (cards, graph, AI conversation).",
};

// Client components handle all interactivity; this page renders the shell
// with static sample fixtures. No auth, no data fetching, no API calls.
export default function ItineraryGraphPrototypePage() {
  const samples = getSampleTimelines();
  return <PrototypeShell samples={samples} />;
}
