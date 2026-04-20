// Route handler that finishes the magic-link loop. Supabase's email template
// sends the user here with either:
//   - a PKCE `code` (current default when using @supabase/ssr), which we
//     exchange for a session via exchangeCodeForSession; or
//   - a legacy `token_hash` + `type` pair, which we verify via verifyOtp.
//
// On success we redirect to /command-center. On failure we bounce back to /
// with an error query so the UI can show a crafted message without leaking
// the raw Supabase error text.

import { NextResponse, type NextRequest } from "next/server";

import { createServerSupabase } from "@/lib/supabase";

function errorRedirect(origin: string, reason: string): NextResponse {
  const url = new URL("/", origin);
  url.searchParams.set("auth_error", reason);
  return NextResponse.redirect(url);
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams, origin } = new URL(request.url);

  const code = searchParams.get("code");
  const tokenHash = searchParams.get("token_hash");
  const otpType = searchParams.get("type");

  // Supabase sets `next` when the app wants to bounce somewhere other than
  // the default. We sanitize to same-origin paths only to avoid open redirect.
  const nextParam = searchParams.get("next") ?? "/command-center";
  const safeNext = nextParam.startsWith("/") ? nextParam : "/command-center";

  const supabase = await createServerSupabase();

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      return errorRedirect(origin, "exchange_failed");
    }
    return NextResponse.redirect(new URL(safeNext, origin));
  }

  if (tokenHash && otpType) {
    const { error } = await supabase.auth.verifyOtp({
      type: otpType as "email" | "magiclink" | "recovery" | "invite" | "signup",
      token_hash: tokenHash,
    });
    if (error) {
      return errorRedirect(origin, "verify_failed");
    }
    return NextResponse.redirect(new URL(safeNext, origin));
  }

  return errorRedirect(origin, "missing_code");
}
