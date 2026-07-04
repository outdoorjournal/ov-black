// The itinerary index (M006/PS3). It lands the planner on the per-trip Dashboard
// — the "you're not lost" home (brief · next action · money · party). Auth +
// fetch + the shell live in the layout; the Dashboard view renders under it.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ItineraryIndexPage({ params }: PageProps) {
  const { id } = await params;
  redirect(`/itinerary/${id}/dashboard`);
}
