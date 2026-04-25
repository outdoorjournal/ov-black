"use client";

import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useRef, useState } from "react";

import { getMapboxToken, loadMapbox, type MapboxMap } from "../_lib/mapbox";

export interface MapFocus {
  lat: number;
  lng: number;
  label?: string;
}

interface MapFlyerProps {
  focus: MapFocus | null;
}

const DEFAULT_CENTER: [number, number] = [138.5, 35.5];

export function MapFlyer({ focus }: MapFlyerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
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
        style: "mapbox://styles/mapbox/light-v11",
        center: DEFAULT_CENTER,
        zoom: 4,
        interactive: false,
        attributionControl: false,
      };
      if (token) opts["accessToken"] = token;
      const map = new mapbox.Map(opts as ConstructorParameters<typeof mapbox.Map>[0]);
      mapRef.current = map;
      map.on("load", () => setReady(true));
    });
    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, [tokenPresent]);

  useEffect(() => {
    if (!ready || !mapRef.current || !focus) return;
    mapRef.current.flyTo({
      center: [focus.lng, focus.lat],
      zoom: 9,
      speed: 0.7,
      curve: 1.4,
      essential: true,
    });
  }, [ready, focus]);

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

function MapFallback({ focus }: { focus: MapFocus | null }) {
  const cx = focus ? ((focus.lng + 180) / 360) * 100 : 50;
  const cy = focus ? ((90 - focus.lat) / 180) * 100 : 50;
  return (
    <div
      className="absolute inset-x-0 bottom-0 h-[62%] transition-all duration-[1200ms] ease-out"
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
