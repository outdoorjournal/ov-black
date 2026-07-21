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
  // Resolve via the API, not `supabase.from("profiles")`: the Supabase Data API
  // (PostgREST) is disabled on the deployed project — apps/api is the only DB
  // surface — so a direct read fails there (it only worked against a local
  // `supabase start`). GET /me/role runs the same profile lookup server-side.
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  if (!accessToken) {
    return "unknown";
  }

  const { apiBaseUrl } = publicEnv();
  try {
    const res = await fetch(`${apiBaseUrl}/me/role`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (!res.ok) {
      return "unknown";
    }
    const body = (await res.json()) as { role?: unknown };
    return body.role === "advisor" || body.role === "client" ? body.role : "unknown";
  } catch {
    return "unknown";
  }
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
  const client = await resolveClientForUser(supabase);
  return client?.clientId ?? null;
}

export type ResolvedClient = {
  clientId: string;
  /** The advisor-entered clients.full_name — the display name for greetings. */
  fullName: string | null;
};

export async function resolveClientForUser(
  supabase: SupabaseClient,
): Promise<ResolvedClient | null> {
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
    const body = (await res.json()) as { client_id?: unknown; full_name?: unknown };
    if (typeof body.client_id !== "string") {
      return null;
    }
    return {
      clientId: body.client_id,
      fullName: typeof body.full_name === "string" ? body.full_name : null,
    };
  } catch {
    return null;
  }
}
