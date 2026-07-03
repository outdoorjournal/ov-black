// Forward-geocoding for inline place chips.
//
// Map chips are authored by the agent as inline markdown links
// (`[Fiskardo](place:Fiskardo)`) — the agent supplies a human search string,
// not coordinates, because it can't be trusted to know lat/lng. We resolve the
// string to a point lazily, the first time a chip is expanded, via Mapbox's
// forward-geocoding endpoint (same public token the map itself uses).
//
// Results are memoised per query for the lifetime of the tab: a chip re-expand
// (or the same place mentioned twice in a thread) never re-hits the network.
// In-flight lookups are shared too, so two chips for the same place opened in
// the same frame make one request.

import { getMapboxToken } from "@/app/_components/itinerary-graph/model/mapbox";

export type GeocodeResult = {
  lng: number;
  lat: number;
  // The canonical name Mapbox resolved to — shown under the map so the user
  // can tell "Kyoto" resolved to Kyoto, Japan and not Kyoto Gardens, London.
  placeName: string;
};

const cache = new Map<string, GeocodeResult | null>();
const inFlight = new Map<string, Promise<GeocodeResult | null>>();

function normalizeQuery(raw: string): string {
  // Agents encode spaces as `+` inside the link destination (markdown link
  // targets are hostile to raw spaces). Undo that, then collapse whitespace.
  return raw.replace(/\+/g, " ").replace(/\s+/g, " ").trim();
}

export async function geocodePlace(rawQuery: string): Promise<GeocodeResult | null> {
  const query = normalizeQuery(rawQuery);
  if (!query) return null;

  const cached = cache.get(query);
  if (cached !== undefined) return cached;

  const pending = inFlight.get(query);
  if (pending) return pending;

  const token = getMapboxToken();
  if (!token) {
    // No token → degrade like MapFlyer does. Cache the null so we don't retry.
    cache.set(query, null);
    return null;
  }

  const promise = (async (): Promise<GeocodeResult | null> => {
    try {
      const url =
        `https://api.mapbox.com/geocoding/v5/mapbox.places/` +
        `${encodeURIComponent(query)}.json?limit=1&access_token=${encodeURIComponent(token)}`;
      const res = await fetch(url);
      if (!res.ok) return null;
      const body: unknown = await res.json();
      const feature =
        body && typeof body === "object"
          ? (body as { features?: unknown }).features
          : undefined;
      const first = Array.isArray(feature) ? feature[0] : undefined;
      if (!first || typeof first !== "object") return null;
      const center = (first as { center?: unknown }).center;
      if (!Array.isArray(center) || center.length < 2) return null;
      const [lng, lat] = center;
      if (typeof lng !== "number" || typeof lat !== "number") return null;
      const placeName =
        typeof (first as { place_name?: unknown }).place_name === "string"
          ? (first as { place_name: string }).place_name
          : query;
      return { lng, lat, placeName };
    } catch {
      return null;
    }
  })();

  inFlight.set(query, promise);
  const result = await promise;
  inFlight.delete(query);
  cache.set(query, result);
  return result;
}
