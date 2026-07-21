// The immersive first-run intake — /itinerary/[id]/new.
//
// A brand-new, traveler-owned adventure lands here instead of any planner
// surface: a full-bleed dark backdrop (the landing page's cinematic imagery
// treatment), Artemis floating in the middle of the page, and a small details
// card that fills in as the conversation captures the adventure's name,
// timing, and party. The agent gathers — it never builds (intake mode).
//
// Deliberately OUTSIDE the (shell) route group: no rail, no concierge column,
// no journal. When the traveler skips or tells Artemis to move on, the chat
// docks left and they land on the trip dashboard — same session, same
// conversation, now in the normal shell.
//
// Fork-first (D030): everything a traveler does belongs on THEIR fork, right
// out of the gate. Visiting this page on a bare trunk creates (or reuses) the
// viewer's open fork, pins the whole intake conversation to it, and every
// agent write (title, brief, timing, party, facts) lands there — the trunk
// stays untouched, and no later edit can ever hit 409 fork_required.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  forkItinerary,
  getItinerary,
  updateItinerary,
} from "@ov-black/api-client";

import { campaignIntake } from "@/lib/campaigns";
import { publicEnv } from "@/lib/env";
import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { IntakeExperience } from "./_components/IntakeExperience";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ campaign?: string }>;
};

export default async function NewItineraryPage({ params, searchParams }: PageProps) {
  const { id: routeId } = await params;
  const { campaign } = await searchParams;

  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/");
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) redirect("/");

  const role = await resolveUserRole(supabase);
  // Advisors keep their in-shell intake form — the immersive conversation is
  // the traveler's front door only.
  if (role === "advisor") redirect(`/itinerary/${routeId}/dashboard`);

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
  const result = await getItinerary(api, routeId);
  if (!result.ok) notFound();

  const isTrunk = !result.itinerary.forked_from_id;
  const isOwnBuild = result.itinerary.created_by === user.id;
  const briefEmpty = (result.itinerary.brief ?? "").trim().length === 0;

  // Resolve the traveler's working copy — the fork the whole intake runs on.
  let target = result;
  if (isTrunk) {
    if (result.viewer_open_fork_id) {
      const fork = await getItinerary(api, result.viewer_open_fork_id);
      if (!fork.ok) notFound();
      target = fork;
    } else if (isOwnBuild && briefEmpty && result.nodes.length === 0) {
      const forked = await forkItinerary(api, routeId);
      if (!forked.ok) redirect(`/itinerary/${routeId}/dashboard`);
      // Forking synthesizes a "{trunk title} (fork)" title — lineage
      // bookkeeping that would read as the trip's name across the dashboard
      // hero and breadcrumbs. Strip the suffix but KEEP the base name: a
      // campaign shell arrives already named (e.g. "Mount Olympus by First
      // Light") and that name must survive even if the agent never renames
      // it. An unnamed trunk's fork reduces to blank; Artemis names that
      // adventure during the conversation.
      const placeholder = (forked.graph.itinerary.title ?? "").trim();
      const baseName = placeholder.replace(/\s*\(fork\)$/i, "").trim();
      if (placeholder !== baseName) {
        await updateItinerary(api, forked.graph.itinerary.id, { title: baseName });
      }
      const fork = await getItinerary(api, forked.graph.itinerary.id);
      if (!fork.ok) notFound();
      target = fork;
    } else {
      // Invited traveler on an advisor-crafted trunk, or an already-briefed
      // trip — intake never gates an established adventure.
      redirect(`/itinerary/${routeId}/dashboard`);
    }
  }

  // Established working copy (brief or cards) → the trip is underway; /new
  // only ever shows while it's genuinely new.
  const established =
    (target.itinerary.brief ?? "").trim().length > 0 || target.nodes.length > 0;
  if (established) {
    redirect(`/itinerary/${target.itinerary.id}/dashboard`);
  }

  // The conversation needs a client to open a session against. A traveler's
  // self-started trip always links their own client row (start-itinerary
  // resolves it); a clientless orphan just falls back to the shell.
  const clientId = target.itinerary.client_id;
  if (!clientId) redirect(`/itinerary/${target.itinerary.id}/dashboard`);

  // Campaign intakes speak in the campaign's voice — headline, eyebrow, and
  // the seeded opener all come from the campaign trim. The itinerary's own
  // campaign_id (stamped at seed time, inherited by forks) is the durable
  // source; the ?campaign= param covers the first hop before hydration.
  const intake = campaignIntake(campaign ?? target.itinerary.campaign_id);

  return (
    <IntakeExperience
      apiBaseUrl={apiBaseUrl}
      accessToken={accessToken}
      clientId={clientId}
      itineraryId={target.itinerary.id}
      trunkId={routeId}
      {...(intake
        ? {
            seededOpener: intake.opener,
            headline: intake.headline,
            eyebrow: intake.eyebrow,
          }
        : {})}
      initial={{
        // The fork of an unnamed trunk carries a placeholder like "(fork)" —
        // that's lineage bookkeeping, not a name. Show "still listening…"
        // until Artemis names the adventure.
        title: (target.itinerary.title ?? "").replace(/\(fork\)\s*$/i, "").trim(),
        timingKind: target.itinerary.timing_kind ?? null,
        dateStart: target.itinerary.date_start ?? null,
        dateEnd: target.itinerary.date_end ?? null,
        durationNights: target.itinerary.duration_nights ?? null,
        timingNote: target.itinerary.timing_note ?? null,
      }}
    />
  );
}
