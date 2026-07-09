"use client";

// Mounts the Command Center's live layer (Wave F): the AdvisorFeed store +
// the SSE transport, wrapped around the whole advisor shell so every surface
// under /command-center shares one stream. Token access follows the
// RightRailChat precedent — browser Supabase session, fresh per connect.

import { useMemo, type ReactNode } from "react";

import { publicEnv } from "@/lib/env";
import { createBrowserSupabase } from "@/lib/supabase/client";
import { useAdvisorFeed } from "@/lib/useAdvisorFeed";

import { AdvisorFeedProvider } from "../_state/advisorFeedStore";

export function AdvisorLiveProvider({ children }: { children: ReactNode }) {
  return (
    <AdvisorFeedProvider initial={undefined}>
      <FeedRunner />
      {children}
    </AdvisorFeedProvider>
  );
}

function FeedRunner() {
  const { apiBaseUrl } = publicEnv();
  const getAccessToken = useMemo<() => Promise<string | null>>(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return async () => {
      if (!supabase) return null;
      const {
        data: { session },
      } = await supabase.auth.getSession();
      return session?.access_token ?? null;
    };
  }, []);

  useAdvisorFeed({ getAccessToken, apiBaseUrl });
  return null;
}
