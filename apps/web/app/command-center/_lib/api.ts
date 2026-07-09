// Server-side API client for advisor pages (Wave F consolidation): every
// /command-center page repeated the getUser → getSession → createApiClient
// dance; this owns it. Auth failure redirects home, matching the layout gate.

import { redirect } from "next/navigation";

import { type Client, createApiClient } from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

export async function advisorApi(): Promise<Client> {
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

  const { apiBaseUrl } = publicEnv();
  return createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );
}
