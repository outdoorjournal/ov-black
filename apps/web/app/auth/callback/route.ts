// Route handler that finishes the magic-link loop. Supabase's email template
// sends the user here with either:
//   - a PKCE `code` (current default when using @supabase/ssr), which we
//     exchange for a session via exchangeCodeForSession; or
//   - a legacy `token_hash` + `type` pair, which we verify via verifyOtp.
//
// After a successful auth, we resolve the user's role via public.profiles and
// branch: advisor → /command-center, client → /chat/[client_id], and fall
// back to / with auth_error=no_client if the clients row can't be resolved.
// If Supabase supplied a same-origin ?next=... override we honor it (used by
// advisor test flows) instead of the role-defaulted destination.

import { NextResponse, type NextRequest } from "next/server";

import { resolveClientIdForUser, resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";
import type { SupabaseClient } from "@supabase/supabase-js";

function errorRedirect(origin: string, reason: string): NextResponse {
  const url = new URL("/", origin);
  url.searchParams.set("auth_error", reason);
  return NextResponse.redirect(url);
}

async function roleAwareRedirect(
  supabase: SupabaseClient,
  origin: string,
  override: string | null,
): Promise<NextResponse> {
  if (override && override.startsWith("/")) {
    return NextResponse.redirect(new URL(override, origin));
  }

  const role = await resolveUserRole(supabase);

  if (role === "advisor") {
    return NextResponse.redirect(new URL("/command-center", origin));
  }

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    return errorRedirect(origin, "no_client");
  }

  return NextResponse.redirect(new URL(`/chat/${clientId}`, origin));
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams, origin } = new URL(request.url);

  const code = searchParams.get("code");
  const tokenHash = searchParams.get("token_hash");
  const otpType = searchParams.get("type");

  // Same-origin ?next=... override. Only honored when it begins with "/" so
  // we can't be tricked into an open redirect.
  const nextParam = searchParams.get("next");
  const nextOverride = nextParam && nextParam.startsWith("/") ? nextParam : null;

  const supabase = await createServerSupabase();

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      return errorRedirect(origin, "exchange_failed");
    }
    return roleAwareRedirect(supabase, origin, nextOverride);
  }

  if (tokenHash && otpType) {
    const { error } = await supabase.auth.verifyOtp({
      type: otpType as "email" | "magiclink" | "recovery" | "invite" | "signup",
      token_hash: tokenHash,
    });
    if (error) {
      return errorRedirect(origin, "verify_failed");
    }
    return roleAwareRedirect(supabase, origin, nextOverride);
  }

  return errorRedirect(origin, "missing_code");
}
