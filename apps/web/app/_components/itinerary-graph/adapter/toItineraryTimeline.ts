// Adapter: API graph (itinerary + nodes + edges) → ItineraryTimeline, the
// view-agnostic shape every graph view consumes. Pure and server-safe — no
// React, no client deps — so the route can run it in an RSC and hand the
// result straight to <ItineraryGraphView>.
//
// The one piece of real work is timing. A view lays nodes onto a per-day,
// minute-of-day axis, so each node needs a `metadata.start_time` (ISO) and a
// `metadata.duration_minutes`. We resolve those, in priority order:
//   1. metadata.start_time / metadata.duration_minutes  (explicit; e.g. an
//      advisor's drag edit persists here, so it must win)
//   2. node.starts_at / node.duration_minutes           (the row's scheduled
//      tstzrange, surfaced by the API)
//   3. synthesis                                          (no timing at all —
//      sequence the node onto the first day so it still renders)
// The resolved values are written back into each node's metadata so the views
// and layout engine read one consistent field regardless of source.

import { tzDayKey } from "../model/time";
import type {
  EdgeResponse,
  ItineraryResponse,
  ItineraryTimeline,
  MoodId,
  NodeResponse,
  NodeType,
} from "../model/types";

// Fields the API exposes on a node row but the generated NodeResponse may not
// be typed for yet (until the client is regenerated). Read defensively so the
// adapter compiles independent of regen timing and stays correct after it.
type TimedNode = NodeResponse & {
  starts_at?: string | null;
  duration_minutes?: number | null;
};

type NodeMetaTiming = {
  start_time?: string;
  duration_minutes?: number;
  [k: string]: unknown;
};

const DEFAULT_MOOD: MoodId = "verdant";

// Sensible per-type fallback durations (minutes) for nodes with no scheduled
// width anywhere. Overnight stays span the night; transit is short.
const DEFAULT_DURATION_MIN: Record<NodeType, number> = {
  flight: 120,
  transit: 45,
  subway: 30,
  train: 90,
  drive: 45,
  walk: 20,
  boat: 60,
  destination: 60,
  hotel: 540,
  experience: 90,
  meal: 90,
  free_time: 120,
  waiting: 30,
  note: 20,
};

// Synthesis anchor for itineraries with zero scheduled nodes: the first
// undated node lands here, the rest follow at 60-min steps.
const SYNTH_START_HOUR = 9;
const SYNTH_STEP_MIN = 60;

export type ToTimelineOptions = {
  mood?: MoodId;
  subtitle?: string;
  // Anchor date (YYYY-MM-DD) for synthesized timing when no node carries a
  // real time. Defaults to today; pass a fixed value in tests for determinism.
  synthAnchorDate?: string;
};

const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

/** Parse the tz offset (in hours, may be fractional) from an ISO string. */
export function parseOffsetHours(iso: string): number | null {
  if (/Z$/.test(iso)) return 0;
  const m = /([+-])(\d{2}):?(\d{2})$/.exec(iso);
  if (!m) return null;
  const sign = m[1] === "-" ? -1 : 1;
  const hh = Number(m[2]);
  const mm = Number(m[3]);
  return sign * (hh + mm / 60);
}

/**
 * Recover the trip's local UTC offset. Node `starts_at` comes back from the
 * tstzrange UTC-normalized (offset lost), but per-type metadata datetimes
 * (flight depart_at/arrive_at, hotel check_in/out, meal seating_at, …) are
 * Pydantic-serialized tz-aware and keep their real offset. We tally every
 * offset-bearing ISO datetime in metadata and pick the most common NON-zero
 * one; UTC-normalized fields contribute 0 and only win if nothing else does.
 * The layout renders local wall-clock as `epoch + offset`, so a correct offset
 * here is what makes a Tokyo trip read 16:10 rather than 07:10.
 */
export function inferTzOffsetHours(nodes: NodeResponse[]): number {
  const tally = new Map<number, number>();
  for (const n of nodes) {
    const meta = (n.metadata ?? {}) as Record<string, unknown>;
    for (const v of Object.values(meta)) {
      if (typeof v !== "string" || !ISO_DATETIME_RE.test(v)) continue;
      const off = parseOffsetHours(v);
      if (off === null) continue;
      tally.set(off, (tally.get(off) ?? 0) + 1);
    }
  }
  let best: number | null = null;
  let bestCount = 0;
  for (const [off, count] of tally) {
    if (off === 0) continue;
    if (count > bestCount) {
      best = off;
      bestCount = count;
    }
  }
  return best ?? 0;
}

function metaOf(node: NodeResponse): NodeMetaTiming {
  return (node.metadata ?? {}) as NodeMetaTiming;
}

// A flight's schedule is INTRINSIC: its own `depart_at` / `arrive_at` are
// authoritative — a departure time isn't a free placement — so they override a
// synthesized layout time and a stale drag-written start/duration (e.g. the
// generic noon + 2h slot a card picks up when placed from the Collection).
// These two readers are the single source of that rule; `explicitStart` and
// `resolveDuration` defer to them so every view (and the metadata written back
// below) sees the real leg.
function flightDepartAt(node: TimedNode): string | null {
  if (node.type !== "flight") return null;
  const d = metaOf(node)["depart_at"];
  return typeof d === "string" && ISO_DATETIME_RE.test(d) ? d : null;
}

function flightLegMinutes(node: TimedNode): number | null {
  const depart = flightDepartAt(node);
  if (depart === null) return null;
  const arrive = metaOf(node)["arrive_at"];
  if (typeof arrive !== "string" || !ISO_DATETIME_RE.test(arrive)) return null;
  const mins = Math.round(
    (new Date(arrive).getTime() - new Date(depart).getTime()) / 60_000,
  );
  return mins > 0 ? mins : null;
}

/** Resolve the explicit (non-synthesized) start, if any. */
function explicitStart(node: TimedNode): string | null {
  const flightStart = flightDepartAt(node);
  if (flightStart !== null) return flightStart;
  const m = metaOf(node);
  if (typeof m.start_time === "string" && m.start_time) return m.start_time;
  if (typeof node.starts_at === "string" && node.starts_at) return node.starts_at;
  return null;
}

function resolveDuration(node: TimedNode): number {
  const leg = flightLegMinutes(node);
  if (leg !== null) return leg;
  const m = metaOf(node);
  if (typeof m.duration_minutes === "number" && m.duration_minutes > 0)
    return m.duration_minutes;
  if (typeof node.duration_minutes === "number" && node.duration_minutes > 0)
    return node.duration_minutes;
  return DEFAULT_DURATION_MIN[node.type] ?? 60;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function offsetSuffix(tzOffsetHours: number): string {
  const sign = tzOffsetHours >= 0 ? "+" : "-";
  const abs = Math.abs(tzOffsetHours);
  return `${sign}${pad(Math.floor(abs))}:${pad(Math.round((abs % 1) * 60))}`;
}

/** Build an ISO timestamp on `dayKey` at `minuteOfDay` in the given tz. */
function isoOnDay(
  dayKey: string,
  minuteOfDay: number,
  tzOffsetHours: number,
): string {
  const mm = Math.max(0, Math.min(1439, Math.round(minuteOfDay)));
  return `${dayKey}T${pad(Math.floor(mm / 60))}:${pad(mm % 60)}:00${offsetSuffix(tzOffsetHours)}`;
}

/** Order nodes by `follows` edges (chain order) where possible, else input order. */
function followOrder(
  nodes: NodeResponse[],
  edges: EdgeResponse[],
): NodeResponse[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const next = new Map<string, string>();
  const hasIncoming = new Set<string>();
  for (const e of edges) {
    if (e.type !== "follows") continue;
    if (!byId.has(e.from_node_id) || !byId.has(e.to_node_id)) continue;
    next.set(e.from_node_id, e.to_node_id);
    hasIncoming.add(e.to_node_id);
  }
  const ordered: NodeResponse[] = [];
  const seen = new Set<string>();
  // Start from nodes with no incoming `follows` edge, in input order.
  for (const n of nodes) {
    if (hasIncoming.has(n.id)) continue;
    let curId: string | undefined = n.id;
    while (curId && !seen.has(curId)) {
      const cur = byId.get(curId);
      if (!cur) break;
      ordered.push(cur);
      seen.add(curId);
      curId = next.get(curId);
    }
  }
  // Append anything not reached (cycles / orphans) in input order.
  for (const n of nodes) if (!seen.has(n.id)) ordered.push(n);
  return ordered;
}

/** Add `days` to a YYYY-MM-DD key, returning a new YYYY-MM-DD key (UTC math). */
function addDaysToKey(dayKey: string, days: number): string {
  const [y, m, d] = dayKey.split("-").map(Number);
  const dt = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
  dt.setUTCDate(dt.getUTCDate() + days);
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}

function diffDays(fromKey: string, toKey: string): number {
  const [fy, fm, fd] = fromKey.split("-").map(Number);
  const [ty, tm, td] = toKey.split("-").map(Number);
  const a = Date.UTC(fy ?? 1970, (fm ?? 1) - 1, fd ?? 1);
  const b = Date.UTC(ty ?? 1970, (tm ?? 1) - 1, td ?? 1);
  return Math.round((b - a) / 86_400_000);
}

function todayKey(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/**
 * Convert an assembled API graph into an ItineraryTimeline. Nodes are returned
 * with `metadata.start_time` and `metadata.duration_minutes` guaranteed set.
 */
export function toItineraryTimeline(
  itinerary: ItineraryResponse,
  nodes: NodeResponse[],
  edges: EdgeResponse[],
  opts: ToTimelineOptions = {},
): ItineraryTimeline {
  const timed = nodes as TimedNode[];

  // tz: prefer an explicit non-UTC offset on a start_time (e.g. an advisor's
  // drag edit writes local time); otherwise infer the trip offset from
  // metadata datetimes; otherwise UTC.
  let tzOffsetHours = inferTzOffsetHours(nodes);
  if (tzOffsetHours === 0) {
    for (const n of timed) {
      const start = explicitStart(n);
      if (start) {
        const off = parseOffsetHours(start);
        if (off !== null && off !== 0) {
          tzOffsetHours = off;
          break;
        }
      }
    }
  }

  // Resolve each node's start/duration, synthesizing for the undated ones.
  // Bucket each node into a day by ITS OWN offset (the trip spans tzs).
  const localDayKey = (iso: string): string =>
    tzDayKey(iso, parseOffsetHours(iso) ?? tzOffsetHours);

  const dated = timed.filter((n) => explicitStart(n) !== null);
  const anchorFromData = dated
    .map((n) => localDayKey(explicitStart(n) as string))
    .sort()[0];
  // First-class trip window (0033): an `exact` itinerary owns real dates, so
  // undated cards should land on the trip and — below — the day span should
  // cover the whole window even before anything is scheduled. `window` /
  // `flexible` stay node-driven; a loose or open-ended range must not fabricate
  // a wall of empty days.
  const exactStart =
    itinerary.timing_kind === "exact" && typeof itinerary.date_start === "string"
      ? itinerary.date_start
      : null;
  const exactEnd =
    itinerary.timing_kind === "exact" && typeof itinerary.date_end === "string"
      ? itinerary.date_end
      : null;
  // Day-1 anchor (0041, ADV-16): the server-stamped date "Day 1" maps to on an
  // unpinned trip, so Day-N numbering survives the Day-1 card being deleted.
  // Read defensively until the generated client carries the field.
  const rawDaysAnchor = (itinerary as { days_anchor?: string | null }).days_anchor;
  const daysAnchor = typeof rawDaysAnchor === "string" && rawDaysAnchor ? rawDaysAnchor : null;
  // An empty unpinned-but-windowed trip lays out from the window's start — the
  // same date the server will stamp as days_anchor when the first card lands,
  // so the provisional layout and the stamped anchor agree.
  const windowStartKey =
    itinerary.timing_kind === "window" && typeof itinerary.date_start === "string"
      ? itinerary.date_start
      : null;

  const synthAnchor =
    opts.synthAnchorDate ??
    exactStart ??
    daysAnchor ??
    anchorFromData ??
    windowStartKey ??
    todayKey();

  // Subgraph children (parent_subgraph_id) are the journey INSIDE a card —
  // the parent owns the slot, so children get no synthesized layout time.
  // They ride through `nodes` untimed for the expandable sub-journey views.
  const undated = followOrder(
    timed.filter((n) => explicitStart(n) === null && !n.parent_subgraph_id),
    edges,
  );
  const synthStartMinute = new Map<string, string>();
  undated.forEach((n, i) => {
    synthStartMinute.set(
      n.id,
      isoOnDay(synthAnchor, SYNTH_START_HOUR * 60 + i * SYNTH_STEP_MIN, tzOffsetHours),
    );
  });

  const resolvedNodes: NodeResponse[] = timed.map((n) => {
    const explicit = explicitStart(n);
    const start = explicit ?? synthStartMinute.get(n.id) ?? null;
    const duration = resolveDuration(n);
    const meta = metaOf(n);
    // Distinguish a REAL placement (an advisor/agent gave it a time) from a
    // SYNTHESIZED one (this node is undated and we're just laying it out so the
    // timeline can render it). The Collection owns undated nodes, so the
    // dominance logic + timeline layout key off this flag rather than the mere
    // presence of a `start_time`.
    const synthesized = explicit === null && start !== null;
    return {
      ...n,
      metadata: {
        ...meta,
        ...(start ? { start_time: start } : {}),
        ...(synthesized ? { start_synthesized: true } : {}),
        duration_minutes: duration,
      },
    };
  });

  // Build the contiguous day span from earliest to latest node date, widened to
  // cover the trip's exact-date window (0033) so a dated-but-empty itinerary
  // still renders its full length. Nodes falling outside the window extend it.
  const nodeDayKeys = resolvedNodes
    .map((n) => (n.metadata as NodeMetaTiming).start_time)
    .filter((s): s is string => typeof s === "string")
    .map((s) => localDayKey(s));
  // The Day-1 anchor joins the span candidates so numbering counts from it
  // (ADV-16): deleting the earliest card must not renumber every other day. A
  // card scheduled BEFORE the anchor still extends the span (render everything).
  const firstDay =
    [
      ...nodeDayKeys,
      ...(exactStart ? [exactStart] : []),
      ...(daysAnchor ? [daysAnchor] : []),
    ].sort()[0] ?? synthAnchor;
  const lastCandidates = [...nodeDayKeys, ...(exactEnd ? [exactEnd] : [])].sort();
  let lastDay = lastCandidates[lastCandidates.length - 1] ?? firstDay;
  // A brand-new (zero-node) adventure without pinned dates still deserves a
  // canvas: scaffold Day 1..N so the Journal renders open days the traveler
  // can start filling. N follows a captured duration (~nights + arrival day)
  // when known, else defaults to a week. Exact-dated trips already span their
  // window above; any first real card re-derives the span node-first.
  if (nodes.length === 0 && !exactStart) {
    const nights = itinerary.duration_nights ?? null;
    const dayCount = Math.min(30, nights && nights > 0 ? nights + 1 : 7);
    lastDay = addDaysToKey(firstDay, dayCount - 1);
  }
  const span = Math.max(0, diffDays(firstDay, lastDay));
  const days = Array.from({ length: span + 1 }, (_, i) => {
    const date = addDaysToKey(firstDay, i);
    return { date, label: `Day ${i + 1}` };
  });

  const windowStart = isoOnDay(firstDay, 0, tzOffsetHours);
  const windowEnd = isoOnDay(lastDay, 24 * 60 - 1, tzOffsetHours);

  return {
    id: itinerary.id,
    label: itinerary.title || "Itinerary",
    subtitle: opts.subtitle ?? "",
    mood: opts.mood ?? DEFAULT_MOOD,
    timezoneOffsetHours: tzOffsetHours,
    windowStart,
    windowEnd,
    days,
    itinerary,
    nodes: resolvedNodes,
    edges,
  };
}
