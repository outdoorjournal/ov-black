// Retired in favour of the unified itinerary graph view. Staff now edit on the
// same surface the traveler sees (/itinerary/[id]), which detects the advisor
// role server-side and unlocks editing. This route redirects so old links /
// bookmarks keep working. The former DraftItineraryEditor component is retained
// only for its unit test; nothing routes to it any more.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function RetiredDraftItineraryPage({ params }: PageProps) {
  const { id } = await params;
  redirect(`/itinerary/${id}`);
}
