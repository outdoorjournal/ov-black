// Client-facing final itinerary view (S09 T03).
//
// This RSC:
//   1. Gates on a live Supabase user — redirects to / if unauthenticated.
//   2. SSR-fetches the assembled graph via getItinerary. The S08 API gate
//      (approved || advisor || owning client) is the source of truth; a
//      `forbidden` detail here means the viewer is not entitled to the
//      draft and the page collapses to notFound() — existence is hidden.
//   3. Hands off to <FinalItineraryView> which is fully server-rendered.
//      No accessToken / apiBaseUrl pass-through — the final view does not
//      fetch anything on the client, so no interactive state is exposed.

import { notFound, redirect } from "next/navigation";

import { createApiClient, getItinerary } from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase";

import { FinalItineraryView } from "./_components/FinalItineraryView";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function FinalItineraryPage({ params }: PageProps) {
  const { id: itineraryId } = await params;

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

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const result = await getItinerary(api, itineraryId);
  if (!result.ok) {
    notFound();
  }

  return (
    <FinalItineraryView
      status={result.itinerary.status ?? "draft"}
      nodes={result.nodes}
      edges={result.edges}
      title={result.itinerary.title}
    />
  );
}
