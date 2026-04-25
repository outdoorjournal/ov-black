// Server-side Supabase client factory for RSCs and route handlers.
//
// @supabase/ssr >= 0.10 expects a getAll / setAll cookie adapter rather than
// the older get/set/remove trio. RSCs cannot mutate cookies, so setAll there
// is a no-op; the middleware and /auth/callback route are the write path.

import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

import { publicEnv } from "../env";

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
