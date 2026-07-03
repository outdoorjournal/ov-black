// Server-side helper that assembles the props the shared AppHeader needs from a
// Supabase session: the viewer's display identity (for the avatar + user menu),
// their application role, and the wordmark's home target for that role.
//
// Keeping this in one place means every app-chrome surface (command-center,
// itinerary, correspondence) shows the SAME identity + home affordance without
// each re-deriving name/avatar from Supabase user_metadata.

import type { SupabaseClient, User } from "@supabase/supabase-js";

import { resolveUserRole, type UserRole } from "./role";

export type AppHeaderUser = {
  email: string;
  name: string | null;
  avatarUrl: string | null;
};

export type AppHeaderContext = {
  user: AppHeaderUser;
  role: UserRole;
  /** Where the wordmark links: advisor → command-center, client → basecamp. */
  homeHref: string;
};

function firstString(...values: unknown[]): string | null {
  for (const v of values) {
    if (typeof v === "string" && v.trim().length > 0) return v;
  }
  return null;
}

/** Pull a display name / avatar out of a Supabase user's metadata. */
export function headerUserFromSupabase(user: User): AppHeaderUser {
  const meta = user.user_metadata ?? {};
  return {
    email: user.email ?? "Signed in",
    name: firstString(meta["full_name"], meta["name"]),
    avatarUrl: firstString(meta["avatar_url"], meta["picture"]),
  };
}

function homeHrefForRole(role: UserRole): string {
  if (role === "advisor") return "/command-center";
  if (role === "client") return "/basecamp";
  return "/";
}

/**
 * Resolve everything the AppHeader needs. Returns null when there is no
 * authenticated user (the caller should redirect). One `getUser()` +
 * one profiles read (via {@link resolveUserRole}).
 */
export async function getAppHeaderContext(
  supabase: SupabaseClient,
): Promise<AppHeaderContext | null> {
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const role = await resolveUserRole(supabase);
  return {
    user: headerUserFromSupabase(user),
    role,
    homeHref: homeHrefForRole(role),
  };
}
