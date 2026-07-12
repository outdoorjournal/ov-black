"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { createApiClient, seedCampaign } from "@ov-black/api-client";

import { CAMPAIGN_INTENT_COOKIE } from "@/lib/campaigns";
import { publicEnv } from "@/lib/env";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Start a trip from an inbound campaign. The CTA in a campaign article links to
 * `/campaign/{slug}`; this seeds the behind-the-scenes shell itinerary (title +
 * brief + hero mood already stamped from the campaign) linked to the caller's
 * own client row, then drops them into the ordinary first-run intake — which is
 * now campaign-aware (the agent opens grounded in the destination).
 *
 * Runs as a server action so the seed + redirect happen on one response with
 * the caller's validated session. Falls back to a normal blank start if the
 * campaign is unknown, so a bad link is never a dead end.
 */
export async function startCampaign(campaignId: string): Promise<void> {
  const supabase = await createServerSupabase();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    // Not signed in yet — remember the campaign so the auth callback can bring
    // them back to it after the magic-link loop, instead of dropping them on a
    // bare /basecamp with the campaign intent lost.
    const jar = await cookies();
    jar.set(CAMPAIGN_INTENT_COOKIE, `/campaign/${campaignId}`, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
      maxAge: 60 * 30, // 30 min — long enough to receive + click the email link.
    });
    redirect("/");
  }

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    // The seed endpoint requires a client to own the itinerary; without one
    // there's nothing to seed against, so fall back to basecamp.
    redirect("/basecamp");
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
  const result = await seedCampaign(api, campaignId, clientId);

  if (!result.ok) {
    redirect("/basecamp");
  }

  // Into the immersive campaign-aware intake, carrying the slug so the opener
  // matches (the agent is already campaign-aware server-side via the directive).
  redirect(`/itinerary/${result.seed.itinerary_id}/new?campaign=${campaignId}`);
}
