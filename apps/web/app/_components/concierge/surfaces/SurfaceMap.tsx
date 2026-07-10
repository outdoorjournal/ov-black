"use client";

// The drawer's map pane — a fuller Mapbox canvas than PlaceChip's inline
// thumbnail. Interactive (pan/zoom) because this surface exists to let the
// traveler actually explore; degrades to the same quiet compass placeholder
// when there's no token or nothing to draw.

// Mapbox's stylesheet must ride along wherever this map renders: without it
// the canvas isn't absolutely positioned (the view drifts off-center) and
// markers aren't clipped to the container (the pin floats over the brief).
import "mapbox-gl/dist/mapbox-gl.css";

import { MapPin } from "lucide-react";
import { useEffect, useRef } from "react";

import {
  applyOvMapTheme,
  getMapboxToken,
  loadMapbox,
  OV_MAP_STYLE,
  type MapboxMap,
} from "@/app/_components/itinerary-graph/model/mapbox";
import type { LngLat } from "@/lib/chat/polyline";
import { cn } from "@/lib/utils";

export type SurfaceMapProps = {
  /** Marker positions ([lng, lat]). A single marker also centers the map. */
  markers?: LngLat[];
  /** Route line ([lng, lat] pairs); when present the map fits its bounds. */
  line?: LngLat[];
  className?: string;
};

const BRAND = "#F5701F";

export function SurfaceMap({ markers = [], line, className }: SurfaceMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const hasToken = Boolean(getMapboxToken());
  const hasGeometry = markers.length > 0 || (line !== undefined && line.length > 1);

  useEffect(() => {
    if (!hasToken || !hasGeometry || !containerRef.current) return;
    let cancelled = false;
    const token = getMapboxToken();

    void loadMapbox().then((mapbox) => {
      if (cancelled || !containerRef.current) return;

      const focus = line?.[0] ?? markers[0];
      if (!focus) return;
      const opts: Record<string, unknown> = {
        container: containerRef.current,
        style: OV_MAP_STYLE,
        center: focus,
        zoom: line ? 9 : 11,
        attributionControl: false,
      };
      if (token) opts["accessToken"] = token;
      const map = new mapbox.Map(opts as ConstructorParameters<typeof mapbox.Map>[0]);
      mapRef.current = map;

      map.on("load", () => {
        if (cancelled) return;
        applyOvMapTheme(map);
        for (const marker of markers) {
          new mapbox.Marker({ color: BRAND }).setLngLat(marker).addTo(map);
        }
        if (line && line.length > 1) {
          map.addSource("surface-route", {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: { type: "LineString", coordinates: line },
            },
          });
          map.addLayer({
            id: "surface-route-line",
            type: "line",
            source: "surface-route",
            layout: { "line-join": "round", "line-cap": "round" },
            paint: { "line-color": BRAND, "line-width": 3, "line-opacity": 0.85 },
          });
          const first = line[0];
          if (first) {
            const bounds = line.reduce(
              (b, coord) => b.extend(coord),
              new mapbox.LngLatBounds(first, first),
            );
            map.fitBounds(bounds, { padding: 48, duration: 0 });
          }
        }
      });
    });

    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
    // Geometry is compared by serialized value: re-instantiating the map on
    // every parent render (new array identities) would flicker it away.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasToken, hasGeometry, JSON.stringify(markers), JSON.stringify(line)]);

  if (hasToken && hasGeometry) {
    return (
      <div
        ref={containerRef}
        data-testid="surface-map"
        className={cn("relative h-64 w-full overflow-hidden bg-ink/5", className)}
      />
    );
  }

  return (
    <div
      data-testid="surface-map-fallback"
      className={cn("flex h-64 w-full items-center justify-center bg-ink/4", className)}
    >
      <MapPin className="h-7 w-7 text-ink/30" aria-hidden />
    </div>
  );
}
