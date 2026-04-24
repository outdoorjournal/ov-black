// Runs on every matched request *before* the RSC renders. Its job is to give
// @supabase/ssr a chance to refresh the Supabase access-token cookie when the
// current one is expiring — without it, the tokens returned by getSession()
// in server components grow stale, and the chat page passes a 1hr-old JWT
// down to the browser where the SSE stream eventually hits 401s.
//
// The getAll/setAll shape here is the @supabase/ssr ≥0.5 contract: we mirror
// refreshed cookies into BOTH the forwarded request (so the RSC reads the
// fresh token on this same request) and the response (so the browser stores
// them for next time). Calling `supabase.auth.getUser()` is what actually
// triggers the refresh — getSession() alone does not.
//
// Matcher excludes Next internals and static assets so we don't pay the
// Supabase round-trip on every /_next/* request.
//
// See: https://supabase.com/docs/guides/auth/server-side/nextjs

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });

  const supabaseUrl = process.env["NEXT_PUBLIC_SUPABASE_URL"];
  const supabaseAnonKey = process.env["NEXT_PUBLIC_SUPABASE_ANON_KEY"];
  if (!supabaseUrl || !supabaseAnonKey) {
    return response;
  }

  const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // Load-bearing: this is what triggers @supabase/ssr to exchange the refresh
  // token when the access token is close to expiry. Do not remove.
  await supabase.auth.getUser();

  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
