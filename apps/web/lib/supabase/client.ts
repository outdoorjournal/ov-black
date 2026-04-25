// Browser-side Supabase client factory. Kept in its own module so client
// components can import it without dragging next/headers (server-only) into
// the browser bundle.

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { publicEnv } from "../env";

export function createBrowserSupabase(): SupabaseClient {
  const { supabaseUrl, supabaseAnonKey } = publicEnv();
  return createBrowserClient(supabaseUrl, supabaseAnonKey);
}
