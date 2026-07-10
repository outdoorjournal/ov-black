import type { Map as MapboxMap } from "mapbox-gl";

import { mapboxToken } from "@/lib/env";

type MapboxModule = typeof import("mapbox-gl");

let cached: MapboxModule | null = null;
let loading: Promise<MapboxModule> | null = null;

export function getMapboxToken(): string | undefined {
  // Runtime config (window.__OVB_ENV__ in the browser); see lib/env.ts.
  return mapboxToken();
}

// Base style we restyle on top of. Mapbox Light is the least busy raster of
// land/water/labels, which makes it the cleanest canvas to recolor.
export const OV_MAP_STYLE = "mapbox://styles/mapbox/light-v11";

// The OV editorial map palette. Mapbox's stock light style is a cold grey/white
// that clashes with the warm paper (#f7f4ee) / ink world the rest of the app
// lives in. We warm every layer into a muted ivory monochrome at runtime so we
// don't have to maintain a Mapbox Studio custom style — the map reads as part
// of the same material as the cards it sits inside.
const OV_MAP = {
  land: "#f3ecdd", // background / base landmass — a touch deeper than paper
  landuse: "#ece3d0", // generic landuse fills
  park: "#e3e3c8", // parks / green space — soft warm sage
  building: "#e7dcc5", // building footprints
  water: "#ccd5d0", // muted warm slate-green — reads as water without cold blue
  road: "#e6dbc4", // minor roads / streets
  roadMajor: "#dccbaa", // motorway / trunk / primary
  border: "#cabd9e", // admin boundaries
  label: "#574f40", // warm taupe ink for text
  labelHalo: "#f7f4ee", // paper halo so labels stay legible over any fill
} as const;

// Recolor the loaded style into the OV palette. Iterates layers by type + id
// keyword rather than hardcoding Mapbox's (versioned) layer names, so it keeps
// working if the base style shifts its internal layer set. Every set is guarded
// because not all paint props exist on every layer.
export function applyOvMapTheme(map: MapboxMap): void {
  const layers = map.getStyle()?.layers;
  if (!layers) return;

  const set = (id: string, prop: string, value: unknown): void => {
    try {
      map.setPaintProperty(id, prop as never, value as never);
    } catch {
      // Layer doesn't support this paint property — skip it.
    }
  };

  for (const layer of layers) {
    const id = layer.id;
    switch (layer.type) {
      case "background":
        set(id, "background-color", OV_MAP.land);
        break;
      case "fill":
        if (/water|ocean|sea|bathymetry/.test(id)) set(id, "fill-color", OV_MAP.water);
        else if (/building/.test(id)) set(id, "fill-color", OV_MAP.building);
        else if (/park|grass|wood|forest|landcover|pitch|green|golf|cemetery|scrub|sand/.test(id))
          set(id, "fill-color", OV_MAP.park);
        else set(id, "fill-color", OV_MAP.landuse);
        break;
      case "line":
        if (/water|river|canal|waterway/.test(id)) set(id, "line-color", OV_MAP.water);
        else if (/admin|boundary|border/.test(id)) set(id, "line-color", OV_MAP.border);
        else if (/motorway|trunk|primary/.test(id)) set(id, "line-color", OV_MAP.roadMajor);
        else if (/road|street|bridge|tunnel|path|rail|transit/.test(id))
          set(id, "line-color", OV_MAP.road);
        break;
      case "symbol":
        set(id, "text-color", OV_MAP.label);
        set(id, "text-halo-color", OV_MAP.labelHalo);
        set(id, "text-halo-width", 1.1);
        break;
    }
  }
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
