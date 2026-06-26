import type { Map as MapboxMap } from "mapbox-gl";

import { mapboxToken } from "@/lib/env";

type MapboxModule = typeof import("mapbox-gl");

let cached: MapboxModule | null = null;
let loading: Promise<MapboxModule> | null = null;

export function getMapboxToken(): string | undefined {
  // Runtime config (window.__OVB_ENV__ in the browser); see lib/env.ts.
  return mapboxToken();
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
