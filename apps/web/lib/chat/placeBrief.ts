// Client-side access to POST /places/brief — server-side place resolution
// (Google Places) + texture (Factbook / Wikipedia) for chips and the drawer.
//
// Self-contained on purpose: it builds its own api-client from the runtime
// public env + the browser Supabase session, so PlaceChip and PlaceSurface
// work identically on every chat surface with zero prop-drilling. Results
// (including misses) are memoised per query for the tab's lifetime and
// in-flight lookups are shared — same policy as lib/chat/geocode.

import { resolvePublicEnv } from "@/lib/env";
import { createBrowserSupabase } from "@/lib/supabase/client";
import { createApiClient, getPlaceBrief, type PlaceBrief } from "@ov-black/api-client";

import { geocodePlace, type GeocodeResult } from "./geocode";

const cache = new Map<string, PlaceBrief | null>();
const inFlight = new Map<string, Promise<PlaceBrief | null>>();

async function accessToken(): Promise<string | null> {
  try {
    const supabase = createBrowserSupabase();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ?? null;
  } catch {
    return null;
  }
}

export async function fetchPlaceBrief(rawQuery: string): Promise<PlaceBrief | null> {
  const query = rawQuery.replace(/\+/g, " ").replace(/\s+/g, " ").trim();
  if (!query) return null;

  const cached = cache.get(query);
  if (cached !== undefined) return cached;
  const pending = inFlight.get(query);
  if (pending) return pending;

  const promise = (async (): Promise<PlaceBrief | null> => {
    const base = resolvePublicEnv().apiBaseUrl;
    if (!base) return null;
    const token = await accessToken();
    if (!token) return null;
    const api = createApiClient({ baseUrl: base, accessToken: token });
    const result = await getPlaceBrief(api, query);
    return result.ok ? result.brief : null;
  })();

  inFlight.set(query, promise);
  const brief = await promise;
  inFlight.delete(query);
  cache.set(query, brief);
  return brief;
}

/**
 * Resolve a loose place string to a point for the small popover fallback.
 * Server-side resolution first (handles the colloquial names the agent
 * writes); Mapbox forward-geocoding only as a last resort.
 */
export async function resolvePlacePoint(query: string): Promise<GeocodeResult | null> {
  const brief = await fetchPlaceBrief(query);
  if (brief) {
    return {
      lng: brief.resolved.lng,
      lat: brief.resolved.lat,
      placeName: brief.resolved.formatted_address || brief.resolved.name,
    };
  }
  return geocodePlace(query);
}
