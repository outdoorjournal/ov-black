"use client";

import "mapbox-gl/dist/mapbox-gl.css";
import type { Marker as MapboxMarker } from "mapbox-gl";
import { useEffect, useRef, useState } from "react";

import {
  applyOvMapTheme,
  getMapboxToken,
  loadMapbox,
  OV_MAP_STYLE,
  type MapboxMap,
} from "../model/mapbox";

export interface MapFocus {
  lat: number;
  lng: number;
  label?: string;
}

export interface MapArc {
  from: [number, number]; // [lng, lat]
  to: [number, number];
}

interface MapFlyerProps {
  focus: MapFocus | null;
  arc?: MapArc | null;
}

const DEFAULT_CENTER: [number, number] = [138.5, 35.5];
const ARC_SOURCE_ID = "ov-arc";
const ARC_LAYER_ID = "ov-arc-line";
const ARC_LAYER_HALO_ID = "ov-arc-halo";

export function MapFlyer({ focus, arc = null }: MapFlyerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const markerRef = useRef<MapboxMarker | null>(null);
  const sourceMarkerRef = useRef<MapboxMarker | null>(null);
  const [ready, setReady] = useState(false);
  const [tokenPresent] = useState(() => Boolean(getMapboxToken()));

  useEffect(() => {
    if (!tokenPresent || !containerRef.current) return;
    let cancelled = false;
    const token = getMapboxToken();
    loadMapbox().then((mapbox) => {
      if (cancelled || !containerRef.current) return;
      const opts: Record<string, unknown> = {
        container: containerRef.current,
        style: OV_MAP_STYLE,
        center: DEFAULT_CENTER,
        zoom: 4,
        interactive: false,
        attributionControl: false,
      };
      if (token) opts["accessToken"] = token;
      const map = new mapbox.Map(opts as ConstructorParameters<typeof mapbox.Map>[0]);
      mapRef.current = map;
      map.on("load", () => {
        applyOvMapTheme(map);
        setReady(true);
      });
    });
    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [tokenPresent]);

  // Marker updates are snappy (apply immediately on focus change). Camera
  // moves are debounced so rapid scroll doesn't restart a new animation every
  // few ms — that's what made the motion look jittery.
  const cameraTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    const map = mapRef.current;

    // Marker: update without delay.
    if (!focus) {
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
    } else {
      void loadMapbox().then((mapbox) => {
        if (!mapRef.current) return;
        if (!markerRef.current) {
          const el = buildMarkerElement();
          markerRef.current = new mapbox.Marker({ element: el, anchor: "center" })
            .setLngLat([focus.lng, focus.lat])
            .addTo(mapRef.current);
        } else {
          markerRef.current.setLngLat([focus.lng, focus.lat]);
        }
      });
    }

    // Camera: debounce + use easeTo (linear pan + zoom interpolation, no
    // zoom-out-then-in fly arc) so close-by hops feel like a single glide.
    if (cameraTimerRef.current) clearTimeout(cameraTimerRef.current);
    if (!focus || arc) return;
    cameraTimerRef.current = setTimeout(() => {
      if (!mapRef.current) return;
      const cur = mapRef.current.getCenter();
      const distSq =
        Math.pow(cur.lng - focus.lng, 2) + Math.pow(cur.lat - focus.lat, 2);
      // Tiny moves (same city) animate quickly; big jumps take longer.
      const duration =
        distSq < 0.05 ? 600 : distSq < 5 ? 900 : 1400;
      map.easeTo({
        center: [focus.lng, focus.lat],
        zoom: 9,
        duration,
        easing: easeOutCubic,
        essential: true,
      });
    }, 140);
  }, [ready, focus, arc]);

  // Arc handling — draw / update / clear the great-circle line. Also debounced.
  const arcTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (arcTimerRef.current) clearTimeout(arcTimerRef.current);
    arcTimerRef.current = setTimeout(() => {
      void loadMapbox().then((mapbox) => {
        if (!mapRef.current) return;
        if (!arc) {
          clearArc(map);
          if (sourceMarkerRef.current) {
            sourceMarkerRef.current.remove();
            sourceMarkerRef.current = null;
          }
          return;
        }
        const points = greatCirclePoints(arc.from, arc.to, 96);
        ensureArcLayers(map, points);
        if (!sourceMarkerRef.current) {
          const el = buildMarkerElement(true);
          sourceMarkerRef.current = new mapbox.Marker({ element: el, anchor: "center" })
            .setLngLat(arc.from)
            .addTo(map);
        } else {
          sourceMarkerRef.current.setLngLat(arc.from);
        }
        const bounds = new mapbox.LngLatBounds(arc.from, arc.from).extend(arc.to);
        map.fitBounds(bounds, {
          padding: { top: 80, bottom: 80, left: 120, right: 80 },
          duration: 1500,
          easing: easeInOutCubic,
          essential: true,
          maxZoom: 7,
        });
      });
    }, 160);
  }, [ready, arc]);

  useEffect(() => {
    return () => {
      if (cameraTimerRef.current) clearTimeout(cameraTimerRef.current);
      if (arcTimerRef.current) clearTimeout(arcTimerRef.current);
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      if (sourceMarkerRef.current) {
        sourceMarkerRef.current.remove();
        sourceMarkerRef.current = null;
      }
    };
  }, []);

  // Easing helpers — cubic feels gentler than Mapbox's default linear ease.
  // (Defined inside the file scope so they're stable references.)

  if (!tokenPresent) {
    return <MapFallback focus={focus} />;
  }

  return (
    <div
      className="absolute inset-0"
      style={{
        opacity: 0.9,
        filter: "saturate(0.9) contrast(0.95)",
      }}
    >
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}

// Builds a small DOM element used as a custom Mapbox marker. Concentric ring +
// soft halo + solid center; halo pulses gently. No JS animation — pure CSS via
// keyframes injected once. `muted` renders a smaller, calmer version used for
// the "from" endpoint of an arc so the destination still reads as primary.
function buildMarkerElement(muted = false): HTMLElement {
  ensureMarkerStyles();
  const wrap = document.createElement("div");
  wrap.className = `ov-marker${muted ? " ov-marker--muted" : ""}`;
  wrap.innerHTML = `
    <span class="ov-marker__halo"></span>
    <span class="ov-marker__ring"></span>
    <span class="ov-marker__dot"></span>
  `;
  return wrap;
}

interface MapboxStyleEditor {
  getSource: (id: string) => { setData: (d: unknown) => void } | undefined;
  addSource: (id: string, src: Record<string, unknown>) => void;
  getLayer: (id: string) => unknown | undefined;
  addLayer: (layer: Record<string, unknown>) => void;
  removeLayer: (id: string) => void;
  removeSource: (id: string) => void;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function greatCirclePoints(
  from: [number, number],
  to: [number, number],
  n: number,
): Array<[number, number]> {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const toDeg = (r: number) => (r * 180) / Math.PI;
  const lng1 = toRad(from[0]);
  const lat1 = toRad(from[1]);
  const lng2 = toRad(to[0]);
  const lat2 = toRad(to[1]);
  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((lat2 - lat1) / 2) ** 2 +
          Math.cos(lat1) *
            Math.cos(lat2) *
            Math.sin((lng2 - lng1) / 2) ** 2,
      ),
    );
  if (d === 0) return [from, to];
  const out: Array<[number, number]> = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lng1) + B * Math.cos(lat2) * Math.cos(lng2);
    const y = A * Math.cos(lat1) * Math.sin(lng1) + B * Math.cos(lat2) * Math.sin(lng2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    out.push([toDeg(Math.atan2(y, x)), toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
  }
  return out;
}

function ensureArcLayers(map: MapboxMap, points: Array<[number, number]>): void {
  const m = map as unknown as MapboxStyleEditor;
  const geojson = {
    type: "Feature" as const,
    properties: {},
    geometry: {
      type: "LineString" as const,
      coordinates: points,
    },
  };
  const existing = m.getSource(ARC_SOURCE_ID);
  if (existing) {
    existing.setData(geojson);
    return;
  }
  m.addSource(ARC_SOURCE_ID, { type: "geojson", data: geojson });
  m.addLayer({
    id: ARC_LAYER_HALO_ID,
    type: "line",
    source: ARC_SOURCE_ID,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "#b88a3e",
      "line-width": 6,
      "line-blur": 6,
      "line-opacity": 0.32,
    },
  });
  m.addLayer({
    id: ARC_LAYER_ID,
    type: "line",
    source: ARC_SOURCE_ID,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "#b88a3e",
      "line-width": 1.6,
      "line-opacity": 0.95,
      "line-dasharray": [2, 1.2],
    },
  });
}

function clearArc(map: MapboxMap): void {
  const m = map as unknown as MapboxStyleEditor;
  for (const id of [ARC_LAYER_ID, ARC_LAYER_HALO_ID]) {
    if (m.getLayer(id)) m.removeLayer(id);
  }
  if (m.getSource(ARC_SOURCE_ID)) m.removeSource(ARC_SOURCE_ID);
}

let stylesInjected = false;
function ensureMarkerStyles(): void {
  if (stylesInjected || typeof document === "undefined") return;
  stylesInjected = true;
  const css = `
    .ov-marker {
      position: relative;
      width: 22px;
      height: 22px;
      pointer-events: none;
    }
    .ov-marker__halo,
    .ov-marker__ring,
    .ov-marker__dot {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      border-radius: 9999px;
    }
    .ov-marker__halo {
      width: 44px;
      height: 44px;
      background: radial-gradient(circle, rgba(184,138,62,0.55) 0%, rgba(184,138,62,0.15) 55%, rgba(184,138,62,0) 75%);
      animation: ov-marker-pulse 2.4s ease-out infinite;
    }
    .ov-marker__ring {
      width: 18px;
      height: 18px;
      border: 1.5px solid rgba(184,138,62,0.85);
      box-shadow: 0 0 0 1px rgba(255,255,255,0.7), 0 1px 4px rgba(0,0,0,0.25);
    }
    .ov-marker__dot {
      width: 7px;
      height: 7px;
      background: #b88a3e;
      box-shadow: 0 0 0 1.5px #f7f4ee, 0 1px 2px rgba(0,0,0,0.4);
    }
    .ov-marker--muted .ov-marker__halo { display: none; }
    .ov-marker--muted .ov-marker__ring {
      width: 12px;
      height: 12px;
      border-color: rgba(184,138,62,0.55);
    }
    .ov-marker--muted .ov-marker__dot {
      width: 5px;
      height: 5px;
      background: rgba(184,138,62,0.85);
    }
    @keyframes ov-marker-pulse {
      0%   { opacity: 0.9; transform: translate(-50%, -50%) scale(0.6); }
      70%  { opacity: 0;   transform: translate(-50%, -50%) scale(1.6); }
      100% { opacity: 0;   transform: translate(-50%, -50%) scale(1.6); }
    }
  `;
  const style = document.createElement("style");
  style.dataset["ovMarkerStyles"] = "1";
  style.textContent = css;
  document.head.appendChild(style);
}

function MapFallback({ focus }: { focus: MapFocus | null }) {
  const cx = focus ? ((focus.lng + 180) / 360) * 100 : 50;
  const cy = focus ? ((90 - focus.lat) / 180) * 100 : 50;
  return (
    <div
      className="absolute inset-x-0 bottom-0 h-[62%] transition-all duration-1200 ease-out"
      style={{
        opacity: 0.6,
        backgroundImage: `radial-gradient(circle at ${cx}% ${cy}%, rgba(180,140,90,0.45), rgba(20,23,61,0.25) 40%, rgba(20,23,61,0) 70%)`,
      }}
    >
      <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
        <svg width="56" height="56" viewBox="0 0 56 56" className="mx-auto text-ink/40" aria-hidden>
          <circle cx="28" cy="28" r="24" fill="none" stroke="currentColor" strokeWidth="0.5" />
          <line x1="28" y1="4" x2="28" y2="52" stroke="currentColor" strokeWidth="0.3" />
          <line x1="4" y1="28" x2="52" y2="28" stroke="currentColor" strokeWidth="0.3" />
          <polygon points="28,8 32,28 28,48 24,28" fill="currentColor" opacity="0.6" />
        </svg>
        {focus ? (
          <p className="mt-2 font-mono text-[10px] tracking-[0.2em] text-ink/60">
            {focus.lat.toFixed(3)}°, {focus.lng.toFixed(3)}°
          </p>
        ) : null}
      </div>
    </div>
  );
}
