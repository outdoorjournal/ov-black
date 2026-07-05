// Server-rendered entry for /basecamp — the client's persistent home.
//
// Branches into one of three variants based on data we resolve here, so the
// browser never flashes the wrong shell:
//   (a) first-touch single prompt — no prior turns, no itineraries
//   (c) post-first-touch + no itineraries — has prior turns, no itineraries
//       (shows a "finish your introduction" reminder until onboarding_complete
//        — the server's one "do we know enough?" verdict — is true)
//   (d) with itineraries — at least one itinerary
// Variant (b) (active conversation) is purely a client-side morph from (a).
//
// Auth posture mirrors /chat/[client_id] — Supabase user + access token
// resolved on the server, no client_id is in the URL because basecamp is
// always self-scoped via the /me/* endpoints.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  getMyOnboardingSession,
  listMyItineraries,
  listTurns,
  pickRandomOpener,
  type AgentTurnSummary,
  type MyItinerarySummary,
  type MyOnboardingSessionResponse,
  type OnboardingOpenerResponse,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { BasecampShell, type BasecampVariant } from "./_components/BasecampShell";

export const dynamic = "force-dynamic";

export default async function BasecampPage() {
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

  const [onboardingResult, itinerariesResult] = await Promise.all([
    getMyOnboardingSession(api),
    listMyItineraries(api),
  ]);

  const onboarding: MyOnboardingSessionResponse = onboardingResult.ok
    ? onboardingResult.session
    : {
        session_id: null,
        turn_count: 0,
        last_turn_at: null,
        seeded_opener: null,
        has_prior_session: false,
        onboarding_complete: false,
      };
  const itineraries: MyItinerarySummary[] = itinerariesResult.ok
    ? itinerariesResult.itineraries
    : [];

  // Gate first-prompt on "any session ever exists" rather than turn_count > 0
  // so a Skip / Close click (which ends the session via /onboarding/dismiss
  // but may produce zero user/assistant turns) is not re-prompted on reload.
  const hasPriorSession = onboarding.has_prior_session || onboarding.turn_count > 0;
  const hasItineraries = itineraries.length > 0;

  // Only fetch an opener when we're going to render the single-prompt UI —
  // the bank lookup is wasted work otherwise, and DevTools-watching
  // verification confirms it skips on returning visits.
  let opener: OnboardingOpenerResponse | null = null;
  let priorTurns: AgentTurnSummary[] = [];
  if (!hasPriorSession && !hasItineraries) {
    const openerResult = await pickRandomOpener(api);
    if (openerResult.ok) {
      opener = openerResult.opener;
    }
  } else if (onboarding.session_id) {
    const turnsResult = await listTurns(api, onboarding.session_id);
    if (turnsResult.ok) {
      priorTurns = turnsResult.turns;
    }
  }

  const variant: BasecampVariant = !hasPriorSession && !hasItineraries
    ? "first_prompt"
    : hasItineraries
    ? "with_itineraries"
    : "post_first_touch";

  return (
    <BasecampShell
      variant={variant}
      user={headerUserFromSupabase(user)}
      clientId={clientId}
      accessToken={accessToken}
      apiBaseUrl={apiBaseUrl}
      opener={opener}
      itineraries={itineraries}
      sessionId={onboarding.session_id}
      priorTurns={priorTurns}
      onboardingComplete={onboarding.onboarding_complete}
    />
  );
}
