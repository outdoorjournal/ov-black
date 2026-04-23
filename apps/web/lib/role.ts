// Resolves the authenticated user's application role by reading a single row
// from public.profiles. The Postgres enum (see apps/api/app/models/profile.py)
// has only 'advisor' and 'client'; we widen to a third 'unknown' bucket so
// callers can distinguish "no profile row yet" from a legitimate client who
// just needs their chat shell. Missing profile rows are expected for freshly
// magic-linked clients whose JIT backfill (see open_or_reuse_session) hasn't
// fired yet, so 'unknown' is not an error condition by itself.

import type { SupabaseClient } from "@supabase/supabase-js";

import { publicEnv } from "./env";

export type UserRole = "advisor" | "client" | "unknown";

export async function resolveUserRole(
  supabase: SupabaseClient,
): Promise<UserRole> {
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return "unknown";
  }

  const { data, error } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .maybeSingle();

  if (error || !data) {
    return "unknown";
  }

  return data.role === "advisor" ? "advisor" : "client";
}

// Delegates to GET /me/client on the API. RLS on public.clients only allows
// advisors to select their own rows, so a freshly magic-linked invitee cannot
// answer "which client row am I?" against Supabase directly. The API endpoint
// runs under service_role and additionally JIT-backfills clients.auth_user_id
// on first hit (email match against the Supabase user's email), which is why
// the callback route calls this exactly once after verifyOtp — subsequent
// visits can hit the fast path.
export async function resolveClientIdForUser(
  supabase: SupabaseClient,
): Promise<string | null> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    return null;
  }

  const { apiBaseUrl } = publicEnv();
  try {
    const res = await fetch(`${apiBaseUrl}/me/client`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (!res.ok) {
      return null;
    }
    const body = (await res.json()) as { client_id?: unknown };
    return typeof body.client_id === "string" ? body.client_id : null;
  } catch {
    return null;
  }
}
