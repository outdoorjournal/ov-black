// Supabase client factories for the Next.js App Router.
//
// We keep three entry points:
//   - createBrowserSupabase(): client components / browser runtime.
//   - createServerSupabase(): React Server Components and route handlers that
//     need to read the current session from request cookies and (in route
//     handlers) write refreshed session cookies back.
//   - cookieAdapter: shared wiring around next/headers' async cookies() API.
//
// @supabase/ssr >= 0.10 expects a getAll / setAll cookie adapter rather than
// the older get/set/remove trio. RSCs cannot mutate cookies, so setAll there
// is a no-op; the middleware and /auth/callback route are the write path.

import { createBrowserClient, createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

import { publicEnv } from "./env";

export function createBrowserSupabase(): SupabaseClient {
  const { supabaseUrl, supabaseAnonKey } = publicEnv();
  return createBrowserClient(supabaseUrl, supabaseAnonKey);
}

export async function createServerSupabase(): Promise<SupabaseClient> {
  const { supabaseUrl, supabaseAnonKey } = publicEnv();
  const cookieStore = await cookies();

  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // RSC render paths cannot mutate cookies. Swallow the error — the
          // next route handler or middleware will refresh the session cookie
          // on the next request.
        }
      },
    },
  });
}
