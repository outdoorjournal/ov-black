import type { Map as MapboxMap } from "mapbox-gl";

type MapboxModule = typeof import("mapbox-gl");

let cached: MapboxModule | null = null;
let loading: Promise<MapboxModule> | null = null;

export function getMapboxToken(): string | undefined {
  // NB: dot-access required — Next.js only inlines `process.env.FOO` syntax into
  // the client bundle; bracket access leaves it `undefined` in production/browser.
  const token = process.env.NEXT_PUBLIC_MAPBOX_API_KEY;
  return token && token.length > 0 ? token : undefined;
}

export async function loadMapbox(): Promise<MapboxModule> {
  if (cached) return cached;
  if (loading) return loading;
  loading = (async () => {
    const mod = (await import("mapbox-gl")) as unknown as MapboxModule & {
      default?: MapboxModule;
    };
    const ns: MapboxModule = mod.default ?? mod;
    cached = ns;
    return ns;
  })();
  return loading;
}

export type { MapboxMap };
