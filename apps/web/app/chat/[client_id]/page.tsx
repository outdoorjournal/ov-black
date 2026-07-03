// Server-rendered entry for /chat/[client_id]. Responsibilities:
//   1. Gate on a live Supabase user (redirect / if absent).
//   2. Fetch the client row via the typed api-client — 404 (notFound) on
//      miss so we mirror the D015 existence-hiding collapse the API already
//      enforces.
//   3. Verify the viewer is either the client themself (auth_user_id match)
//      or the owning advisor. Any other shape collapses to notFound() for
//      the same reason.
//   4. Open / reuse the agent session via POST /sessions and hydrate any
//      prior turns via GET /sessions/{id}/turns so a page reload doesn't
//      lose conversation history.
//   5. Hand it all off to the <ChatShell> client component which takes over
//      the streaming UI.
//
// Notes on authz: resolveUserRole treats missing profiles as "unknown" —
// a freshly magic-linked client whose JIT backfill hasn't produced a
// profiles row yet still falls into the auth_user_id equality branch on
// the clients row check below, so they can reach their shell on first
// visit. The JIT backfill from T01/T02 fires inside open_or_reuse_session,
// so subsequent visits resolve the advisor/client split cleanly.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  createSessionEndpoint,
  getClient,
  getItinerary,
  listTurns,
  type AgentTurnSummary,
} from "@ov-black/api-client";

import { AppHeader, type Crumb } from "@/app/_components/app-header/AppHeader";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { publicEnv } from "@/lib/env";
import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { ChatShell } from "./_components/ChatShell";
import { cardFromNode, type InitialCardPayload } from "./_components/types";

// The shell is user-specific and session-specific — never cache it.
export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ client_id: string }>;
};

export default async function ChatPage({ params }: PageProps) {
  const { client_id: clientId } = await params;

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
    // Auth says we have a user but no token — treat as D015 rather than
    // crashing the render. The user is bumped back to /auth/callback by the
    // normal cookie-refresh cycle on the next navigation.
    redirect("/");
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  // The /clients/{id} endpoint is advisor-scoped. We use it to verify an
  // advisor viewer AND to pick up the display name. For a client-viewer
  // (themself), the request returns 403/404 — that's fine, we fall back to
  // a minimal header and rely on POST /sessions for authz.
  const clientResult = await getClient(api, clientId);

  // POST /sessions is the load-bearing authz + JIT-backfill surface: it
  // opens the session if the caller is either the owning advisor OR the
  // client themself, and 404s otherwise with the D015 shape. This also
  // fires the T01/T02 JIT backfill for freshly magic-linked clients.
  const sessionResult = await createSessionEndpoint(api, { client_id: clientId });
  if (!sessionResult.ok) {
    // 404 / validation / network all collapse to notFound() — the API
    // already enforces existence-hiding, so we don't add extra copy here.
    notFound();
  }

  // Display name fallback: if getClient 404'd (client-viewer-of-self), the
  // chat header just reads "Your concierge" rather than leaking a name we
  // don't have server-side authz to read.
  const clientForShell = clientResult.ok
    ? { id: clientResult.client.id, full_name: clientResult.client.full_name }
    : { id: clientId, full_name: "Your concierge" };

  // Replay prior turns AND prior MoodBoard cards in parallel — this is the
  // reload path. A brand-new session returns empty lists and the ChatShell
  // auto-fires a bootstrap opener turn on mount. itinerary_id is non-null
  // here in practice (open_or_reuse_session eagerly creates one for the
  // chat path) but is typed as nullable for the basecamp call site.
  const itineraryId = sessionResult.itinerary_id;
  if (itineraryId === null) {
    notFound();
  }
  const [turnsResult, itineraryResult] = await Promise.all([
    listTurns(api, sessionResult.session_id),
    getItinerary(api, itineraryId),
  ]);
  const initialTurns: AgentTurnSummary[] = turnsResult.ok ? turnsResult.turns : [];
  const initialCards: InitialCardPayload[] = itineraryResult.ok
    ? itineraryResult.nodes
        .map(cardFromNode)
        .filter((c): c is InitialCardPayload => c !== null)
    : [];

  // Shared masthead over the immersive chat. Advisors reach it from their
  // client; a client-of-self reaches it from basecamp. The big serif client
  // name stays as the page title beneath the header.
  const role = await resolveUserRole(supabase);
  const homeHref = role === "advisor" ? "/command-center" : "/basecamp";
  const crumbs: Crumb[] =
    role === "advisor"
      ? [
          { label: "Clients", href: "/command-center/clients" },
          {
            label: clientForShell.full_name,
            href: `/command-center/clients/${clientId}`,
          },
          { label: "Correspondence" },
        ]
      : [{ label: "Basecamp", href: "/basecamp" }, { label: "Correspondence" }];

  return (
    <ChatShell
      sessionId={sessionResult.session_id}
      accessToken={accessToken}
      apiBaseUrl={apiBaseUrl}
      client={clientForShell}
      initialTurns={initialTurns}
      itineraryId={itineraryId}
      initialCards={initialCards}
      header={
        <AppHeader
          user={headerUserFromSupabase(user)}
          homeHref={homeHref}
          crumbs={crumbs}
        />
      }
    />
  );
}
