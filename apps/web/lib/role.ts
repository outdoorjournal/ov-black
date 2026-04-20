// Resolves the authenticated user's application role by reading a single row
// from public.profiles. The Postgres enum (see apps/api/app/models/profile.py)
// has only 'advisor' and 'client'; we widen to a third 'unknown' bucket so
// callers can distinguish "no profile row yet" from a legitimate client who
// just needs their chat shell. Missing profile rows are expected for freshly
// magic-linked clients whose JIT backfill (see open_or_reuse_session) hasn't
// fired yet, so 'unknown' is not an error condition by itself.

import type { SupabaseClient } from "@supabase/supabase-js";

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

export async function resolveClientIdForUser(
  supabase: SupabaseClient,
): Promise<string | null> {
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return null;
  }

  const { data, error } = await supabase
    .from("clients")
    .select("id")
    .eq("auth_user_id", user.id)
    .maybeSingle();

  if (error || !data) {
    return null;
  }

  return data.id as string;
}
