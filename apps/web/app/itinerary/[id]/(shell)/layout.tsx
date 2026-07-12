// The itinerary planner shell layout (M006/PS1). Owns everything that must
// persist across a switch between planning destinations (timeline / collection /
// studio): the auth + fetch, the shared AppHeader, and the client ItineraryShell
// that hosts the graph store Provider + the persistent concierge. Child routes
// render into the shell's planning space.
//
// The Provider was lifted here (out of the retired ItineraryBuilderScreen /
// ItineraryGraphView chain) precisely so the store — and the open concierge —
// survive view navigation; `key={itineraryId}` gives each trip a fresh store
// while sibling-route nav reuses the same one. The visibility gate (S08) still
// collapses a non-entitled viewer to notFound() so a draft's existence stays
// hidden — now guarding the whole segment from the layout.

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { createApiClient, getItinerary } from "@ov-black/api-client";

import { AppHeader, type Crumb } from "@/app/_components/app-header/AppHeader";
import { toItineraryTimeline } from "@/app/_components/itinerary-graph/adapter/toItineraryTimeline";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { publicEnv } from "@/lib/env";
import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { ItineraryShell } from "../_shell/ItineraryShell";

export const dynamic = "force-dynamic";

type LayoutProps = {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
  // The @modal parallel slot — the card-detail intercepting route ((.)item/
  // [nodeId]) renders into it, empty (default.tsx) otherwise. Rendered inside
  // ItineraryShell so the modal shares the graph store + concierge.
  modal: React.ReactNode;
};

export default async function ItineraryLayout({
  params,
  children,
  modal,
}: LayoutProps) {
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
  const status = result.itinerary.display_status ?? "in_studio";
  const isTrunk = !result.itinerary.forked_from_id;
  const isOwnBuild = result.itinerary.created_by === user.id;

  // Solo traveler: their working copy IS the trip. An empty trunk they started
  // themselves defaults into their open fork rather than a blank official view.
  if (
    role !== "advisor" &&
    isTrunk &&
    isOwnBuild &&
    result.nodes.length === 0 &&
    result.viewer_open_fork_id
  ) {
    redirect(`/itinerary/${result.viewer_open_fork_id}`);
  }

  // Invited traveler on an advisor-crafted trunk with nothing published yet:
  // the timeline shows the "being crafted" teaser instead of the builder
  // empty state (which is the self-serve prompt).
  const awaitingProposal = role !== "advisor" && isTrunk && !isOwnBuild;

  // Immersive first-run intake (traveler-only): a brand-new adventure the
  // viewer started — no brief, no cards yet — lands on /new, the full-screen
  // conversation with Artemis, instead of any planner surface. A trunk with
  // an open fork already bounced to the fork above, so this fires on the
  // bare trunk or on the (still-blank) fork itself. /new sets the dismissal
  // cookie on skip / move-on so the redirect never loops within the browser
  // session.
  const briefEmpty = (result.itinerary.brief ?? "").trim().length === 0;
  const intakePending =
    role !== "advisor" && isOwnBuild && briefEmpty && result.nodes.length === 0;
  if (intakePending) {
    const jar = await cookies();
    if (!jar.get(`ovb-intake-dismissed-${itineraryId}`)) {
      redirect(`/itinerary/${itineraryId}/new`);
    }
  }

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

  // Shared masthead: wordmark → trip title → avatar menu. The return-home crumb
  // ("Basecamp" / "Clients") now lives at the top of the rail (PS7), so the
  // header carries only the current trip — one crumb, not a nav trail.
  const tripTitle = result.itinerary.title?.trim() || "Itinerary";
  const homeHref = role === "advisor" ? "/command-center" : "/basecamp";
  const crumbs: Crumb[] = [{ label: tripTitle }];

  return (
    <div className="flex h-dvh flex-col bg-paper">
      <AppHeader
        user={headerUserFromSupabase(user)}
        homeHref={homeHref}
        crumbs={crumbs}
      />
      <ItineraryShell
        // A fresh store per trip; sibling-route nav keeps the same instance.
        key={itineraryId}
        timeline={timeline}
        baselineTitle={baselineTitle}
        itineraryId={itineraryId}
        status={status}
        role={role}
        // Each viewer gets their OWN session token: advisors use it to mutate,
        // travelers use it to chat with the concierge. Capability is governed by
        // `role` (UI) + the backend's advisor guards (authority).
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        viewerOpenForkId={result.viewer_open_fork_id ?? null}
        awaitingProposal={awaitingProposal}
        totals={result.totals}
        displayCurrency={result.display_currency ?? null}
        totalDisplay={result.total_display ?? null}
      >
        {children}
        {modal}
      </ItineraryShell>
    </div>
  );
}
