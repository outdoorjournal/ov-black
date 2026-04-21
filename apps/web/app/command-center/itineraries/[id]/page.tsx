// Advisor-facing draft itinerary editor (S08 T05).
//
// This RSC:
//   1. Gates on a live Supabase user — redirects to / if unauthenticated.
//   2. SSR-fetches the assembled graph via getItinerary. The API gate
//      (_is_requester_advisor || owning_client) is the source of truth for
//      who is allowed to see a draft; a `forbidden` detail here means the
//      viewer is neither.
//   3. Hands off to the <DraftItineraryEditor> client component with the
//      flat graph + itinerary status. Lock state is local to the editor —
//      acquireItineraryLock on mount + optimistic flips on Edit/Release/
//      Approve buttons.
//
// The editor is intentionally advisor-shaped: there is no client-facing
// read of the draft graph here (clients hit /chat, which uses the approved
// MoodBoard aside). Craft-feel discipline (R014) forbids spinners, icons,
// emoji, or skeletons inside [data-testid='draft-itinerary-editor'].

import { notFound, redirect } from "next/navigation";

import { createApiClient, getItinerary } from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase";

import { DraftItineraryEditor } from "./_components/DraftItineraryEditor";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function DraftItineraryPage({ params }: PageProps) {
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
    // 404 and 403 both collapse to notFound() — the API already enforces
    // existence hiding for the draft-read gate, so leaking an "access
    // denied" copy on the advisor surface only confuses the rare case
    // where the URL is stale.
    notFound();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-10 px-6 py-12">
      <header className="flex items-end justify-between gap-6">
        <div>
          <h1 className="font-serif text-4xl tracking-tight text-ink">
            {result.itinerary.title || "Concierge draft"}
          </h1>
          <p className="mt-2 font-sans text-xs uppercase tracking-[0.3em] text-ink/60">
            Draft itinerary
          </p>
        </div>
      </header>

      <DraftItineraryEditor
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        initialNodes={result.nodes}
        initialEdges={result.edges}
        initialStatus={result.itinerary.status ?? "draft"}
      />
    </main>
  );
}
