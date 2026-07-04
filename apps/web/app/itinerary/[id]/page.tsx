// The itinerary index (M006/PS1). No surface of its own yet — it lands the
// planner on the Timeline. PS3 replaces this with the per-trip Dashboard (the
// "you're not lost" home). Auth + fetch + the shell live in the layout.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ItineraryIndexPage({ params }: PageProps) {
  const { id } = await params;
  redirect(`/itinerary/${id}/timeline`);
}
