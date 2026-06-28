// Unified itinerary graph route (traveler + staff).
//
// Both the traveler and an advisor land here on the SAME view. The server
// resolves the viewer's `role` and passes it straight through — the store
// derives editability from it (advisor → editable). Each viewer is handed
// their OWN Supabase session token (already in their browser), so:
//   - traveler → role=client: the editing UI stays locked, but the token
//                powers the traveler-facing concierge (chat) and the read-only
//                graph.
//   - advisor  → role=advisor: the lock/approve/edit/add/remove mutations call
//                the API. The backend's advisor guards remain the real
//                authority over every mutation regardless of the UI.
// Passing the viewer their own token leaks nothing — it is the same JWT they
// already hold; what we never do is hand one viewer another's credentials.
//
// The S08 API gate (approved || advisor || owning client) on GET /itinerary
// is the source of truth for *visibility*; a non-entitled viewer collapses to
// notFound() so a draft's existence stays hidden.

import { notFound, redirect } from "next/navigation";

import { createApiClient, getItinerary } from "@ov-black/api-client";

import { ItineraryGraphView } from "@/app/_components/itinerary-graph/ItineraryGraphView";
import { toItineraryTimeline } from "@/app/_components/itinerary-graph/adapter/toItineraryTimeline";
import { publicEnv } from "@/lib/env";
import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function ItineraryPage({ params }: PageProps) {
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

  const role = await resolveUserRole(supabase);
  const status = result.itinerary.status ?? "draft";
  const timeline = toItineraryTimeline(
    result.itinerary,
    result.nodes,
    result.edges,
  );

  // When this is an alternative version (a fork, G3), resolve the baseline's
  // title so the banner can name the agreed plan it diverges from.
  let baselineTitle: string | null = null;
  if (result.itinerary.forked_from_id) {
    const baseline = await getItinerary(api, result.itinerary.forked_from_id);
    if (baseline.ok) baselineTitle = baseline.itinerary.title;
  }

  return (
    <ItineraryGraphView
      timeline={timeline}
      itineraryId={itineraryId}
      status={status}
      role={role}
      baselineTitle={baselineTitle}
      // Each viewer gets their OWN session token: advisors use it to mutate,
      // travelers use it to chat with the concierge. Capability is governed by
      // `role` (UI) + the backend's advisor guards (authority).
      apiBaseUrl={apiBaseUrl}
      accessToken={accessToken}
    />
  );
}
