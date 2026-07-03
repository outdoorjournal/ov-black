"use server";

import { redirect } from "next/navigation";

import { createApiClient, createItinerary } from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Start a brand-new itinerary and drop the caller into its builder. This is the
 * traveler's self-serve entry point (also usable by an advisor): it creates an
 * empty itinerary linked to the caller's own client row, then redirects to
 * `/itinerary/{id}`, where the first-run intake captures the brief + timing.
 *
 * Runs as a server action so the create + redirect happen on one response with
 * the caller's validated session — no client-side SDK round-trip.
 */
export async function startNewItinerary(): Promise<void> {
  const supabase = await createServerSupabase();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    redirect("/");
  }

  // Link the itinerary to the caller's own client so it shows up as theirs and
  // the owner write-gate admits them when they save the brief. `null` is fine
  // for an advisor with no client row of their own — creator-ownership still
  // admits them.
  const clientId = await resolveClientIdForUser(supabase);

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
  const result = await createItinerary(api, { title: "", client_id: clientId });

  if (!result.ok) {
    // Couldn't create — send them back to basecamp rather than a dead end.
    redirect("/basecamp");
  }

  redirect(`/itinerary/${result.itinerary.id}`);
}
