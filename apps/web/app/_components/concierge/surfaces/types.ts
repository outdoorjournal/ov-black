// Drawer-surface view models + tolerant wire parsing.
//
// A `surface` SSE frame carries `{surface_id, kind, payload}` with the payload
// left as an unknown-record at the transport layer (lib/agentStream.types).
// This module narrows it per kind, parseTimeline-style: anything malformed
// returns null and the panel simply doesn't open — a bad payload must never
// crash the stream. The `place` surface has no frame at all; it opens
// client-side when a PlaceChip is tapped and fetches its own brief.

import type { SurfaceFrame } from "@/lib/agentStream";

export type RouteLegView = {
  distanceMeters: number;
  durationSeconds: number;
  startLat?: number;
  startLng?: number;
  endLat?: number;
  endLng?: number;
};

export type RouteHighlightView = {
  title: string;
  detail?: string;
};

export type RouteSurfaceView = {
  origin: string;
  destination: string;
  waypoints: string[];
  mode: string;
  distanceMeters: number;
  durationSeconds: number;
  encodedPolyline: string;
  legs: RouteLegView[];
  headline?: string;
  highlights: RouteHighlightView[];
};

export type OptionView = {
  id: string;
  title: string;
  tagline?: string;
  case?: string;
  nodeId?: string;
};

export type OptionsSurfaceView = {
  question: string;
  context?: string;
  options: OptionView[];
};

export type ArticleSurfaceView = {
  title: string;
  url: string;
  publication?: string;
  ogImage?: string;
  excerpt?: string;
  readingTimeMinutes?: number;
};

export type ActiveSurface =
  | { kind: "place"; label: string; query: string }
  | { kind: "route"; surfaceId: string; route: RouteSurfaceView }
  | { kind: "options"; surfaceId: string; options: OptionsSurfaceView }
  | { kind: "article"; surfaceId: string; article: ArticleSurfaceView };

// ── Parsing helpers ──────────────────────────────────────────────────────

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function rec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function parseRoute(payload: Record<string, unknown>): RouteSurfaceView | null {
  const route = rec(payload["route"]);
  if (!route) return null;
  const origin = str(route["origin"]);
  const destination = str(route["destination"]);
  const encodedPolyline = str(route["encoded_polyline"]);
  if (!origin || !destination || !encodedPolyline) return null;

  const legs: RouteLegView[] = [];
  const rawLegs = route["legs"];
  if (Array.isArray(rawLegs)) {
    for (const raw of rawLegs) {
      const leg = rec(raw);
      if (!leg) continue;
      const view: RouteLegView = {
        distanceMeters: num(leg["distance_meters"]) ?? 0,
        durationSeconds: num(leg["duration_seconds"]) ?? 0,
      };
      const startLat = num(leg["start_lat"]);
      const startLng = num(leg["start_lng"]);
      const endLat = num(leg["end_lat"]);
      const endLng = num(leg["end_lng"]);
      if (startLat !== undefined) view.startLat = startLat;
      if (startLng !== undefined) view.startLng = startLng;
      if (endLat !== undefined) view.endLat = endLat;
      if (endLng !== undefined) view.endLng = endLng;
      legs.push(view);
    }
  }

  const highlights: RouteHighlightView[] = [];
  const rawHighlights = payload["highlights"];
  if (Array.isArray(rawHighlights)) {
    for (const raw of rawHighlights) {
      const h = rec(raw);
      const title = h ? str(h["title"]) : undefined;
      if (!h || !title) continue;
      const detail = str(h["detail"]);
      highlights.push({ title, ...(detail ? { detail } : {}) });
    }
  }

  const waypoints = Array.isArray(route["waypoints"])
    ? route["waypoints"].filter((w): w is string => typeof w === "string")
    : [];
  const headline = str(payload["headline"]);

  return {
    origin,
    destination,
    waypoints,
    mode: str(route["mode"]) ?? "drive",
    distanceMeters: num(route["distance_meters"]) ?? 0,
    durationSeconds: num(route["duration_seconds"]) ?? 0,
    encodedPolyline,
    legs,
    ...(headline ? { headline } : {}),
    highlights,
  };
}

function parseOptions(payload: Record<string, unknown>): OptionsSurfaceView | null {
  const question = str(payload["question"]);
  if (!question) return null;
  const rawOptions = payload["options"];
  if (!Array.isArray(rawOptions)) return null;

  const options: OptionView[] = [];
  for (const raw of rawOptions) {
    const o = rec(raw);
    if (!o) continue;
    const id = str(o["id"]);
    const title = str(o["title"]);
    if (!id || !title) continue;
    const tagline = str(o["tagline"]);
    const caseText = str(o["case"]);
    const nodeId = str(o["node_id"]);
    options.push({
      id,
      title,
      ...(tagline ? { tagline } : {}),
      ...(caseText ? { case: caseText } : {}),
      ...(nodeId ? { nodeId } : {}),
    });
  }
  if (options.length < 2) return null;

  const context = str(payload["context"]);
  return { question, options, ...(context ? { context } : {}) };
}

function parseArticle(payload: Record<string, unknown>): ArticleSurfaceView | null {
  // Title + url are the load-bearing fields: without them there's nothing to
  // show and nothing to save. Everything else enriches the flyout.
  const title = str(payload["title"]);
  const url = str(payload["url"]);
  if (!title || !url) return null;
  const publication = str(payload["publication"]);
  const ogImage = str(payload["og_image"]);
  const excerpt = str(payload["excerpt"]);
  const readingTimeMinutes = num(payload["reading_time_minutes"]);
  return {
    title,
    url,
    ...(publication ? { publication } : {}),
    ...(ogImage ? { ogImage } : {}),
    ...(excerpt ? { excerpt } : {}),
    ...(readingTimeMinutes !== undefined ? { readingTimeMinutes } : {}),
  };
}

/**
 * Narrow a wire `surface` frame into an ActiveSurface, or null when the kind
 * is unknown (a newer agent talking to an older client — drop quietly) or
 * the payload is unusable.
 */
export function surfaceFromFrame(frame: SurfaceFrame): ActiveSurface | null {
  if (frame.kind === "route") {
    const route = parseRoute(frame.payload);
    return route ? { kind: "route", surfaceId: frame.surface_id, route } : null;
  }
  if (frame.kind === "options") {
    const options = parseOptions(frame.payload);
    return options ? { kind: "options", surfaceId: frame.surface_id, options } : null;
  }
  if (frame.kind === "article") {
    const article = parseArticle(frame.payload);
    return article ? { kind: "article", surfaceId: frame.surface_id, article } : null;
  }
  return null;
}
