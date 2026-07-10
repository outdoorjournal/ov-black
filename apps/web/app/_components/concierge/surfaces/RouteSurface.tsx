"use client";

// The route mini-brochure — how the journey from A to B actually works.
//
// Geometry (polyline, distances, durations) comes from Google Routes via the
// backend; the agent authors only the headline and highlight notes. The map
// draws the decoded polyline with markers on each leg boundary; beneath it,
// the verifiable facts line, then the agent's notes, then a per-leg breakdown
// when the route has intermediate stops.

import { decodePolyline, type LngLat } from "@/lib/chat/polyline";

import { SurfaceMap } from "./SurfaceMap";
import type { RouteSurfaceView } from "./types";

const MODE_LABEL: Record<string, string> = {
  drive: "by car",
  walk: "on foot",
  bicycle: "by bicycle",
  transit: "by train & transit",
};

export function formatDistance(meters: number): string {
  if (meters <= 0) return "";
  if (meters < 1000) return `${meters} m`;
  const km = meters / 1000;
  return km >= 100 ? `${Math.round(km)} km` : `${km.toFixed(1).replace(/\.0$/, "")} km`;
}

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return "";
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes === 0 ? `${hours} hr` : `${hours} hr ${minutes} min`;
}

export function RouteSurface({ route }: { route: RouteSurfaceView }) {
  const line = decodePolyline(route.encodedPolyline);
  const markers = legMarkers(route, line);
  const facts = [
    formatDistance(route.distanceMeters),
    formatDuration(route.durationSeconds),
    MODE_LABEL[route.mode] ?? route.mode,
  ]
    .filter(Boolean)
    .join(" · ");

  const stops = [route.origin, ...route.waypoints, route.destination];

  return (
    <div data-testid="route-surface">
      <SurfaceMap markers={markers} line={line} />

      <div className="px-6 py-5">
        {route.headline ? (
          <h2 className="font-serif text-2xl leading-snug text-ink">{route.headline}</h2>
        ) : null}
        <p className="mt-1 font-sans text-[13px] text-ink/70">
          <span className="text-ink">{route.origin}</span>
          <span className="text-ink/40"> → </span>
          <span className="text-ink">{route.destination}</span>
        </p>
        {facts ? (
          <p
            className="mt-1 font-sans text-[12px] uppercase tracking-[0.14em] text-ink/50"
            data-testid="route-surface-facts"
          >
            {facts}
          </p>
        ) : null}

        {route.highlights.length > 0 ? (
          <ul className="mt-5 space-y-3" data-testid="route-surface-highlights">
            {route.highlights.map((highlight) => (
              <li key={highlight.title} className="grid grid-cols-[auto_1fr] gap-x-3">
                <span
                  aria-hidden
                  className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                />
                <span>
                  <span className="block font-serif text-[15px] leading-snug text-ink">
                    {highlight.title}
                  </span>
                  {highlight.detail ? (
                    <span className="mt-0.5 block font-sans text-[13px] leading-snug text-ink/60">
                      {highlight.detail}
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {route.legs.length > 1 ? (
          <section className="mt-6" data-testid="route-surface-legs">
            <h3 className="font-sans text-[10px] uppercase tracking-[0.22em] text-ink/45">
              Leg by leg
            </h3>
            <ol className="mt-2 space-y-1.5">
              {route.legs.map((leg, i) => (
                <li key={i} className="font-sans text-[13px] leading-snug text-ink/70">
                  <span className="text-ink">
                    {stops[i] ?? `Leg ${i + 1}`}
                    <span className="text-ink/40"> → </span>
                    {stops[i + 1] ?? ""}
                  </span>
                  <span className="text-ink/50">
                    {" — "}
                    {[formatDistance(leg.distanceMeters), formatDuration(leg.durationSeconds)]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </div>
    </div>
  );
}

// Markers at the route's endpoints and each leg boundary. When legs carry no
// usable coordinates, fall back to the polyline's own ends.
function legMarkers(route: RouteSurfaceView, line: LngLat[]): LngLat[] {
  const markers: LngLat[] = [];
  for (const leg of route.legs) {
    if (leg.startLng !== undefined && leg.startLat !== undefined) {
      markers.push([leg.startLng, leg.startLat]);
    }
  }
  const last = route.legs[route.legs.length - 1];
  if (last && last.endLng !== undefined && last.endLat !== undefined) {
    markers.push([last.endLng, last.endLat]);
  }
  if (markers.length === 0 && line.length > 1) {
    const first = line[0];
    const end = line[line.length - 1];
    if (first) markers.push(first);
    if (end) markers.push(end);
  }
  return markers;
}
