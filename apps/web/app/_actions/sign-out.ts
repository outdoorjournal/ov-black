"use server";

import { redirect } from "next/navigation";

import { createServerSupabase } from "@/lib/supabase/server";

/**
 * Clears the Supabase session cookies and returns the user to the landing
 * page. Runs as a server action so the cookie writes land on the same
 * response as the redirect — no client SDK round-trip and no flash of an
 * authed shell after sign-out.
 *
 * App-wide: invoked from the shared AppHeader's user menu across every
 * app-chrome surface (command-center, itinerary, correspondence) and from
 * the client-facing BasecampChrome.
 */
export async function signOutAction(): Promise<void> {
  const supabase = await createServerSupabase();
  await supabase.auth.signOut();
  redirect("/");
}
