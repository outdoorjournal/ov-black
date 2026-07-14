// Traveler reading list (/basecamp/reading).
//
// A dedicated magazine rack for the "article" nodes a traveler has saved to
// their itinerary Collections (via the agent's save_link_to_collection, kind
// "article"). Self-scoped like the rest of basecamp: we resolve every trip from
// /me/itineraries, then read each trip's graph and lift out its article nodes,
// so the page spans the whole account rather than a single itinerary.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  getItinerary,
  listMyItineraries,
  type MyItinerarySummary,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";
import {
  dedupeReadingItems,
  isReadingArticle,
  toReadingItem,
  type ReadingItem,
} from "@/app/_components/reading/readingItem";

import { BasecampChrome } from "../_components/BasecampChrome";
import { ReadingRack } from "./_components/ReadingRack";

export const dynamic = "force-dynamic";

export default async function ReadingPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/");
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    redirect("/");
  }

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    notFound();
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const itinerariesResult = await listMyItineraries(api);
  const itineraries: MyItinerarySummary[] = itinerariesResult.ok
    ? itinerariesResult.itineraries
    : [];

  // Read every trip's graph in parallel and lift out its article nodes. A
  // traveler has a handful of trips, so the fan-out is cheap; a failed graph
  // read just contributes nothing rather than sinking the page.
  const perTrip = await Promise.all(
    itineraries.map(async (it) => {
      const graph = await getItinerary(api, it.id);
      if (!graph.ok) return [] as ReadingItem[];
      return graph.nodes.filter(isReadingArticle).map(toReadingItem);
    }),
  );

  const items = dedupeReadingItems(perTrip.flat());

  return (
    <BasecampChrome user={headerUserFromSupabase(user)}>
      <ReadingRack items={items} apiBaseUrl={apiBaseUrl} accessToken={accessToken} />
    </BasecampChrome>
  );
}
