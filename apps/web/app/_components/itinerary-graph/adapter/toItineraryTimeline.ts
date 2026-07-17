// Adapter: API graph (itinerary + nodes + edges) → ItineraryTimeline, the
// view-agnostic shape every graph view consumes. Pure and server-safe — no
// React, no client deps — so the route can run it in an RSC and hand the
// result straight to <ItineraryGraphView>.
//
// The one piece of real work is timing. A view lays nodes onto a per-day,
// minute-of-day axis, so each node needs a `metadata.start_time` (ISO), a
// `metadata.day_key` (its day column), and a `metadata.duration_minutes`.
// Since Phase 4 (doc/itin-time.md) the SERVER resolves time: every node
// arrives with a `schedule` view (day_index, per-endpoint local date / wall
// time / zone, absolute instant — synthesized slots included for unscheduled
// cards), so this adapter projects rather than derives. Start resolution, in
// priority order:
//   1. metadata.start_time / metadata.duration_minutes  (the server's own
//      mirror of the schedule — and where optimistic drag edits land, so it
//      must win)
//   2. node.schedule                                     (the kernel-resolved
//      view: real placements and synthesized Collection slots)
//   3. node.starts_at / node.duration_minutes            (legacy rows with no
//      decodable schedule)
//   4. local synthesis                                    (fallback for nodes
//      that bypassed the server view entirely)
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
  day_key?: string;
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
  article: 20,
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

  // tz: the trip's default offset comes from the SERVER-resolved instants —
  // each `schedule.start.instant` is serialized in its own zone, so its
  // offset is exact, not inferred. Fall back to an explicit start's own
  // offset for legacy nodes with no schedule view; otherwise UTC. Only used
  // for offset-less strings and the window bounds — every server-resolved
  // node carries its own offset end to end.
  let tzOffsetHours = 0;
  for (const n of timed) {
    const instant = n.schedule?.start.instant;
    const off = instant ? parseOffsetHours(instant) : null;
    if (off !== null && off !== 0) {
      tzOffsetHours = off;
      break;
    }
  }
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

  // The date "Day 1" maps to — the server's kernel anchor when it has one
  // (Phase 4), else the same provisional chain the layout uses, so a
  // day_index projected here agrees with what the server stamps on the first
  // placement. Exposed as `dayOneKey` so the store can convert a drop's
  // visual dayKey into a kernel day_index.
  const rawAnchorDate = (itinerary as { anchor_date?: string | null }).anchor_date;
  const dayOneKey =
    (typeof rawAnchorDate === "string" && rawAnchorDate ? rawAnchorDate : null) ??
    exactStart ??
    daysAnchor ??
    windowStartKey ??
    synthAnchor;

  // The server computes a provisional slot for every unscheduled root card
  // (`schedule.synthesized` — Phase 4); project it onto the calendar. A
  // relative slot on a fully undated trip carries no instant, so it lands on
  // the same provisional Day-1 the layout uses.
  const serverSynthStart = (n: TimedNode): string | null => {
    const s = n.schedule;
    if (!s?.synthesized) return null;
    if (s.start.instant) return s.start.instant;
    const [hh, mm] = s.start.wall_time.split(":").map(Number);
    return isoOnDay(
      addDaysToKey(dayOneKey, (s.start.day_index ?? 1) - 1),
      (hh ?? 9) * 60 + (mm ?? 0),
      tzOffsetHours,
    );
  };

  // Subgraph children (parent_subgraph_id) are the journey INSIDE a card —
  // the parent owns the slot, so children get no synthesized layout time.
  // They ride through `nodes` untimed for the expandable sub-journey views.
  // Local synthesis remains only for nodes the server gave no view (e.g. a
  // graph payload predating Phase 4).
  const undated = followOrder(
    timed.filter(
      (n) => explicitStart(n) === null && !n.parent_subgraph_id && serverSynthStart(n) === null,
    ),
    edges,
  );
  const synthStartMinute = new Map<string, string>();
  undated.forEach((n, i) => {
    synthStartMinute.set(
      n.id,
      isoOnDay(synthAnchor, SYNTH_START_HOUR * 60 + i * SYNTH_STEP_MIN, tzOffsetHours),
    );
  });

  // The day column a node belongs to — the server's resolved day when the
  // start being rendered IS the server's, else derived from the start string's
  // own offset (optimistic drag edits, legacy rows).
  const dayKeyFor = (n: TimedNode, start: string | null): string | null => {
    if (start === null) return null;
    const s = n.schedule;
    if (s?.start != null) {
      const sameInstant =
        s.start.instant !== null &&
        s.start.instant !== undefined &&
        new Date(s.start.instant).getTime() === new Date(start).getTime();
      if (sameInstant || s.start.instant == null) {
        if (typeof s.start.date === "string" && s.start.date) return s.start.date;
        if (typeof s.start.day_index === "number")
          return addDaysToKey(dayOneKey, s.start.day_index - 1);
      }
    }
    return localDayKey(start);
  };

  const resolvedNodes: NodeResponse[] = timed.map((n) => {
    const explicit = explicitStart(n);
    const start = explicit ?? serverSynthStart(n) ?? synthStartMinute.get(n.id) ?? null;
    const duration = resolveDuration(n);
    const meta = metaOf(n);
    // Distinguish a REAL placement (an advisor/agent gave it a time) from a
    // SYNTHESIZED one (this node is undated and we're just laying it out so the
    // timeline can render it). The Collection owns undated nodes, so the
    // dominance logic + timeline layout key off this flag rather than the mere
    // presence of a `start_time`.
    const synthesized = explicit === null && start !== null;
    const dayKey = dayKeyFor(n, start);
    return {
      ...n,
      metadata: {
        ...meta,
        ...(start ? { start_time: start } : {}),
        ...(dayKey ? { day_key: dayKey } : {}),
        ...(synthesized ? { start_synthesized: true } : {}),
        duration_minutes: duration,
      },
    };
  });

  // Build the contiguous day span from earliest to latest node date, widened to
  // cover the trip's exact-date window (0033) so a dated-but-empty itinerary
  // still renders its full length. Nodes falling outside the window extend it.
  const nodeDayKeys = resolvedNodes
    .map((n) => (n.metadata as NodeMetaTiming).day_key)
    .filter((s): s is string => typeof s === "string");
  // The Day-1 anchor joins the span candidates so numbering counts from it
  // (ADV-16): deleting the earliest card must not renumber every other day. A
  // card scheduled BEFORE the anchor still extends the span (render everything).
  // On a PINNED (exact) trip `date_start` IS Day 1 — a stale pre-pin
  // `days_anchor` (e.g. stamped against a scratch note added before dates were
  // set) must NOT inject phantom leading days, so exactStart wins and the
  // anchor is never both. Mirrors time.ts `dayAnchorKey`.
  const anchorKey = exactStart ?? daysAnchor;
  const firstDay =
    [...nodeDayKeys, ...(anchorKey ? [anchorKey] : [])].sort()[0] ?? synthAnchor;
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
    dayOneKey,
    itinerary,
    nodes: resolvedNodes,
    edges,
  };
}
