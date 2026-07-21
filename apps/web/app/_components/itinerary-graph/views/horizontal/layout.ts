// Horizontal-layout math.
//
// Big idea: each day is its own column laid out left-to-right. All day columns
// share a single y axis whose unit is *minute of day* (0..1440), so 09:00 in
// day 1 sits at exactly the same y as 09:00 in day 8 — you can scan
// horizontally to compare "what was I doing at 10am on each day" and the
// shared sun gradient + weather strip on the left labels them once.
//
// Strategy: **uniform timeline with elision**. Live regions scale linearly
// with zoom — `(end−start) × pxPerMinute` — so the timeline compresses
// evenly when the user zooms out. Dead stretches collapse to a fixed elision
// band so the day fits at any zoom — but ONLY the night/evening shoulders
// (before `DAY_START_MIN` / after `DAY_END_MIN`). Empty *daytime* time stays
// live and full-height so there's always somewhere to drop an afternoon plan;
// otherwise a sparse day crams its two cards together over a 56px band and the
// hours between them aren't droppable. No per-slot min-row-height inflation: a slot
// containing a tall glance card doesn't add real-estate. Start times still
// snap to a 15-minute grid for clean lane assignment. To stop short events
// from visually overlapping their neighbors at low zoom, each card
// independently switches to a compact strip form when its time-distance to
// the next card in lane × pxPerMinute drops below `GLANCE_MIN_HEIGHT_PX`.
//
// Night bars (overnight sleep) don't take card-width; they render as a thin
// colored strip pinned to the right edge of each day column from local-21:00
// to the column's bottom.

import type { EdgeResponse, NodeResponse } from "../../model/horizontalTypes";
import { getHMeta } from "../../model/horizontalTypes";
import {
  MINUTES_PER_DAY,
  formatMinuteOfDay,
  localMinuteOfDay,
  offsetHoursOr,
  tzDayKey,
} from "../../model/horizontalTime";
import {
  beatImageForChild,
  isSubgraphChild,
  subgraphChildrenByParent,
  subgraphDayMeta,
} from "../../shared/subgraph";

export const TIME_GUTTER = 96;
// PAD_X reserves space for the first day's duration-bar gutter; otherwise the
// 16px bar at xOf(p) - 20 would overhang the canvas's left edge.
export const PAD_X = 24;
export const PAD_TOP = 12;
export const DAY_HEADER_HEIGHT = 64;
// Matches CardShell glance width (`w-[260px]`) in /prototype/cards so the
// focused/dragging chrome wraps the visible card edge exactly. Compact
// cards share the same 260px footprint — only their vertical height
// collapses, since the compact trigger is low *vertical* density per-card,
// not horizontal pressure.
export const LANE_WIDTH = 260;
export const LANE_GAP = 12;
export const COL_WIDTH = LANE_WIDTH;

// Per-card compact rule: room = (nextInLane.startMin − this.startMin) ×
// effectivePxPerMin. Pure time-distance in pixels — no slot inflation —
// so the rule scales linearly with zoom (down to the floor where the
// compact tile fits in 15 min). Threshold is roughly the upper end of a
// glance card body: experience cards with image + chips are ~230 px,
// transit/hotel ~166 px, so 180 catches all but the tallest with a
// little overlap acceptable for outliers.
export const GLANCE_MIN_HEIGHT_PX = 180;
export const COL_GAP = 20;
export const NIGHT_BAR_WIDTH = 6;
export const NIGHT_BAR_GAP = 4;
export const CARD_FALLBACK_H = 132;
export const VERTICAL_PAD = 8;

// Snap grid. Start times round to the nearest `SNAP_SLOT_MIN` minutes so
// lane assignment and card positions land on clean quarter-hour boundaries.
export const SNAP_SLOT_MIN = 15;

// Empty runs longer than this collapse to a fixed-height elision band —
// but only outside the active-day window (see below).
const ELIDE_THRESHOLD_MIN = 90;
const ELIDE_BAND_PX = 56;

// Active-day window. Empty stretches *inside* [DAY_START_MIN, DAY_END_MIN]
// never elide — they stay live so an advisor can always drop a card into an
// open afternoon. Only the shoulders (early morning / evening / overnight)
// collapse. Generous bounds (07:00–21:00) so early-evening plans still land on
// real, droppable time; genuinely late/overnight dead air is what compresses.
const DAY_START_MIN = 7 * 60;
const DAY_END_MIN = 21 * 60;

// Where a day-derived subgraph beat (an unscheduled "day k" leg) lands on its
// morning — matches the Journal's `BEAT_START_TIME` so the two views agree.
const BEAT_MORNING_MIN = 9 * 60;

// "HH:MM" (a beat's authored `subgraph_day.hhmm`) → minute of day.
function hhmmToMinute(s: string): number {
  const [h, m] = s.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

// The ISO offset suffix of `iso`, or one built from the trip default. A derived
// beat's `start_time` must carry an offset — an offset-less ISO is parsed in
// the BROWSER's zone and re-rendered in the trip's, drifting the displayed
// clock by the difference. Mirrors the Journal's `offsetSuffixOf`.
function offsetSuffixOf(iso: string, tzDefault: number): string {
  const m = iso.match(/(Z|[+-]\d{2}:\d{2})$/);
  if (m?.[1]) return m[1];
  const sign = tzDefault < 0 ? "-" : "+";
  const abs = Math.abs(tzDefault);
  const pad2 = (n: number) => String(n).padStart(2, "0");
  return `${sign}${pad2(Math.floor(abs))}:${pad2(Math.round((abs % 1) * 60))}`;
}

export interface TimelineSegment {
  type: "live" | "elide";
  startMin: number;
  endMin: number;
  yStart: number;
  yEnd: number;
}

export interface PositionedHNode {
  node: NodeResponse;
  dayKey: string;
  dayIndex: number; // 0-based index into the days array
  lane: number;
  x: number;
  y: number;
  w: number;
  cardH: number;
  barH: number;
  // True when the card's duration at the current zoom doesn't give it
  // enough vertical room for a glance card — render compact strip instead.
  compact: boolean;
  nightBar?: boolean;
  altGroup?: string;
  altGroupMembers?: string[];
}

export interface DayLayout {
  date: string;
  dayIndex: number;
  columnX: number;
  columnWidth: number;
  label: string;
  weather_emoji?: string | undefined;
}

// A multi-day item's presence on a day AFTER its start day. The card itself
// stays on the start day; each covered day gets a gutter bar from midnight
// down to where the item ends that day (or the column bottom when it runs
// through), plus a small clickable chip so the day doesn't read as empty.
export interface ContinuationSpan {
  node: NodeResponse;
  dayKey: string;
  dayIndex: number;
  // Lane-0 x of the day column (same coordinate space as PositionedHNode.x).
  x: number;
  w: number;
  y: number;
  barH: number;
  // Minute-of-day the span ends on this day (1440 when it runs past midnight
  // again into the next day).
  endMin: number;
  // True when the item actually ends on this day (chip shows the end time).
  isFinal: boolean;
  dayOfSpan: number; // 1-based: start day is 1, first continuation is 2, …
  spanDays: number;
}

// A subgraph child (a "day k of N" leg of a packaged multi-day experience,
// carrying `parent_subgraph_id`) laid onto the timeline as a beat that rides
// its PARENT's start-finish line — never a card of its own. Placed at the
// child's real local time when it carries a `starts_at`, else derived from its
// `subgraph_day.index` (day 1 rides the parent's start; later days step forward
// morning by morning), mirroring the Journal's journey beats.
export interface SubgraphBeat {
  parentId: string;
  childId: string;
  title: string;
  // The child node, enriched with the parent's imagery (mirrors the Journal's
  // journey beats) so the timeline can render it as a full glance card with a
  // photo rather than a bare chip. Its `start_time`/`duration_minutes` are set
  // to the beat's resolved placement so the card's own clock/duration read true.
  node: NodeResponse;
  dayKey: string;
  dayIndex: number;
  // Lane-0 x of the day column (same coordinate space as PositionedHNode.x) —
  // the beat sits on the parent's bar, which lives in this column's gutter.
  x: number;
  w: number;
  y: number;
  startMin: number;
  // Active hours the leg runs, when the vendor states them — feeds the chip's
  // sublabel ("~7h").
  hours?: number;
  // True when the beat sits at a real scheduled time (vs. a day-derived one).
  scheduled: boolean;
}

export interface TimeMarker {
  y: number;
  label: string;
}

export interface HLayoutResult {
  positions: Map<string, PositionedHNode>;
  continuations: ContinuationSpan[];
  subgraphBeats: SubgraphBeat[];
  segments: TimelineSegment[];
  days: DayLayout[];
  totalWidth: number;
  totalHeight: number;
  pxPerMinute: number;
  tzOffsetHours: number;
  altGroups: Map<string, string[]>;
  timeMarkers: TimeMarker[];
}

interface LayoutArgs {
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pxPerMinute: number;
  tzOffsetHours: number;
  daysMeta: Array<{ date: string; label: string; weather_emoji?: string }>;
  cardHeights?: Map<string, number>;
  // When a drag is in flight, the dragged node's id is passed here so the
  // layout treats its old slot as vacant: other cards in its day collapse
  // around it instead of being pushed into a side lane, and the ghost-node
  // version of the dragged card competes for lanes against everyone else
  // *without* the dragged source still holding lane 0.
  excludeNodeId?: string;
}

function snapMinute(m: number): number {
  return Math.round(m / SNAP_SLOT_MIN) * SNAP_SLOT_MIN;
}

export function mapMinuteToY(min: number, segments: TimelineSegment[]): number {
  for (const seg of segments) {
    if (min < seg.startMin) return seg.yStart;
    if (min < seg.endMin) {
      const range = seg.endMin - seg.startMin || 1;
      const t = (min - seg.startMin) / range;
      return seg.yStart + t * (seg.yEnd - seg.yStart);
    }
  }
  const last = segments[segments.length - 1];
  return last ? last.yEnd : 0;
}

// Inverse of mapMinuteToY — translates a drag's pointer-y back into a clock
// minute. Elide bands collapse onto the band's end minute so a drop into a
// dead gap snaps to the nearest live edge.
export function mapYToMinute(y: number, segments: TimelineSegment[]): number {
  if (segments.length === 0) return 0;
  const first = segments[0];
  if (first && y < first.yStart) return first.startMin;
  for (const seg of segments) {
    if (y < seg.yEnd) {
      if (seg.type === "elide") return seg.endMin;
      const range = seg.yEnd - seg.yStart || 1;
      const t = (y - seg.yStart) / range;
      return seg.startMin + t * (seg.endMin - seg.startMin);
    }
  }
  const last = segments[segments.length - 1];
  return last ? last.endMin : 0;
}

export function computeHorizontalLayout(args: LayoutArgs): HLayoutResult {
  const {
    nodes,
    edges,
    pxPerMinute,
    tzOffsetHours,
    daysMeta,
    cardHeights,
    excludeNodeId,
  } = args;

  const laneWidth = LANE_WIDTH;

  // Alt groups: from metadata or from `alternative_to` edges. Same shape as
  // the vertical layout — a set of node ids that should be visually grouped.
  // In this prototype we *don't* fan them into separate lanes; they stack
  // vertically like everything else, and the alt-group key is preserved on
  // each PositionedHNode so the renderer can paint a soft cluster border.
  const altGroupByNode = new Map<string, string>();
  for (const n of nodes) {
    const m = getHMeta(n);
    if (m.alt_group) altGroupByNode.set(n.id, m.alt_group);
  }
  for (const e of edges) {
    if (e.type === "alternative_to") {
      const groupKey = altGroupByNode.get(e.to_node_id) ?? `alt-${e.to_node_id}`;
      altGroupByNode.set(e.to_node_id, groupKey);
      altGroupByNode.set(e.from_node_id, groupKey);
    }
  }
  const altGroups = new Map<string, string[]>();
  for (const [nodeId, group] of altGroupByNode.entries()) {
    const arr = altGroups.get(group) ?? [];
    arr.push(nodeId);
    altGroups.set(group, arr);
  }

  const dayIndexByDate = new Map<string, number>();
  daysMeta.forEach((d, i) => dayIndexByDate.set(d.date, i));

  interface Item {
    node: NodeResponse;
    meta: ReturnType<typeof getHMeta>;
    dayKey: string;
    dayIndex: number;
    startMin: number; // snapped
    rawStartMin: number; // original, for night-bar y if needed
    durationMin: number;
    cardH: number;
    isNightBar: boolean;
    compact: boolean;
  }

  // Compact form's single-row card height. Used as the cardH fallback for
  // items whose compact decision flipped before they were measured.
  const compactFallbackH = 44;

  const items: Item[] = [];
  for (const n of nodes) {
    const m = getHMeta(n);
    // Subgraph children never take a card/lane of their own — they ride the
    // parent's start-finish line as beats (built below), even when they carry
    // a real `starts_at`. Skip them here so a scheduled leg doesn't render as
    // an independent timeline card competing for lanes.
    if (isSubgraphChild(n)) continue;
    if (!m.start_time) continue;
    // Synthesized placements are Collection items, not timeline cards — the
    // rail renders them. Skip so they don't double-render onto the timeline.
    if (m.start_synthesized) continue;
    // Each node is placed by ITS OWN local wall-clock (a trip spans tzs), so
    // resolve the offset from the node's start_time and only fall back to the
    // trip-level default when the string carries none. The day column comes
    // from the stamped `day_key` (server-resolved, Phase 4) when present.
    const nodeTz = offsetHoursOr(m.start_time, tzOffsetHours);
    const stampedDayKey = (m as { day_key?: unknown }).day_key;
    const dayKey =
      typeof stampedDayKey === "string" && stampedDayKey
        ? stampedDayKey
        : tzDayKey(m.start_time, nodeTz);
    const dayIndex = dayIndexByDate.get(dayKey);
    if (dayIndex === undefined) continue;
    const rawStartMin = localMinuteOfDay(m.start_time, nodeTz);
    const isNightBar = Boolean(m.night_bar);
    // Night bars aren't snapped: they pin to the column edge and don't
    // contribute to slot height; snapping them would just shift their top
    // edge for no visual benefit.
    const startMin = isNightBar ? rawStartMin : snapMinute(rawStartMin);
    const durationMin =
      typeof m.duration_minutes === "number" ? m.duration_minutes : 30;
    // Card height starts at the glance fallback; the pass-1 segments use
    // this to estimate "if everyone were glance, how much room would each
    // card have?". After pass 1 we revise both `compact` and `cardH`.
    const measured = cardHeights?.get(n.id);
    const cardH =
      typeof measured === "number" && measured > 0
        ? Math.max(measured, CARD_FALLBACK_H)
        : CARD_FALLBACK_H;
    items.push({
      node: n,
      meta: m,
      dayKey,
      dayIndex,
      startMin,
      rawStartMin,
      durationMin,
      cardH,
      isNightBar,
      compact: false,
    });
  }

  // Per-day lane assignment based on snapped-time overlap. Cards whose
  // [startMin, startMin+duration] intervals collide go to successively higher
  // lanes (rendered side-by-side in the same day column). Night bars do not
  // participate — they live in the column's right-edge strip and never
  // compete with cards for lane room. While a drag is in flight, the
  // dragged source is excluded so its old position doesn't push the ghost
  // into a second lane during a same-day reorder.
  const laneByNode = new Map<string, number>();
  const dayLaneCount = new Map<string, number>();
  {
    const itemsByDay = new Map<string, Item[]>();
    for (const it of items) {
      if (it.isNightBar) continue;
      if (excludeNodeId && it.node.id === excludeNodeId) continue;
      const arr = itemsByDay.get(it.dayKey) ?? [];
      arr.push(it);
      itemsByDay.set(it.dayKey, arr);
    }
    for (const [dayKey, dayItems] of itemsByDay.entries()) {
      const indexed = dayItems.map((it, i) => ({ it, i }));
      indexed.sort((a, b) =>
        a.it.startMin === b.it.startMin
          ? a.i - b.i
          : a.it.startMin - b.it.startMin,
      );
      const laneEnd: number[] = [];
      for (const { it } of indexed) {
        const end = it.startMin + it.durationMin;
        let lane = -1;
        for (let li = 0; li < laneEnd.length; li++) {
          const prev = laneEnd[li];
          if (typeof prev === "number" && prev <= it.startMin) {
            lane = li;
            laneEnd[li] = end;
            break;
          }
        }
        if (lane === -1) {
          lane = laneEnd.length;
          laneEnd.push(end);
        }
        laneByNode.set(it.node.id, lane);
      }
      dayLaneCount.set(dayKey, Math.max(1, laneEnd.length));
    }
    if (excludeNodeId) laneByNode.set(excludeNodeId, 0);
  }

  // Per-card compact decision: room = time-distance to the next card in
  // this lane × pxPerMinute. For the last item in a lane there's no next,
  // so room is treated as "rest of day" — practically unlimited, so
  // glance. The rule is linear in zoom: at pxPerMinute=0.6 a 2-hour event
  // has 72 px of room (compact), at 1.5 it has 180 px (glance).
  const itemsByLane = new Map<string, Item[]>();
  for (const item of items) {
    if (item.isNightBar) continue;
    const lane = laneByNode.get(item.node.id) ?? 0;
    const key = `${item.dayKey}|${lane}`;
    const arr = itemsByLane.get(key) ?? [];
    arr.push(item);
    itemsByLane.set(key, arr);
  }
  for (const arr of itemsByLane.values()) {
    arr.sort((a, b) => a.startMin - b.startMin);
  }
  // Floor the effective scale so a 15-minute live span is at least as tall
  // as a compact tile. Below this, the user's slider stops compressing the
  // timeline — there's no useful way to render two compact cards 15 min
  // apart in fewer pixels than the cards themselves occupy. Compact
  // decisions use the same effective scale so the rule and the rendering
  // stay consistent.
  const effectivePxPerMin = Math.max(
    pxPerMinute,
    compactFallbackH / SNAP_SLOT_MIN,
  );

  for (const arr of itemsByLane.values()) {
    for (let i = 0; i < arr.length; i++) {
      const cur = arr[i]!;
      const next = arr[i + 1];
      const gapMin = next ? next.startMin - cur.startMin : MINUTES_PER_DAY;
      const room = gapMin * effectivePxPerMin;
      cur.compact = room < GLANCE_MIN_HEIGHT_PX;
      const measured = cardHeights?.get(cur.node.id);
      const fallback = cur.compact ? compactFallbackH : CARD_FALLBACK_H;
      cur.cardH =
        typeof measured === "number" && measured > 0 ? measured : fallback;
    }
  }

  // Uniform timeline with elision. Live regions (where any card lands,
  // plus a small buffer) scale linearly with zoom: `(end−start) ×
  // pxPerMinute`. Dead stretches longer than ELIDE_THRESHOLD_MIN
  // (overnight) collapse to a fixed-height band so the day fits.
  const segments: TimelineSegment[] = (() => {
    const NODE_BUFFER_MIN = 15;
    const intervals: Array<[number, number]> = [];
    for (const item of items) {
      if (item.isNightBar) continue;
      const endAbs = item.startMin + item.durationMin;
      // A multi-day item "occupies" its nights, but the y axis is SHARED
      // across every day column — letting it keep the whole night live would
      // stretch every day in the trip. So a spanning item only claims live
      // time up to the day-end shoulder; its bar compresses through the
      // elided night, which is exactly the "continues overnight" read.
      const intervalEnd =
        endAbs > MINUTES_PER_DAY
          ? Math.min(
              MINUTES_PER_DAY,
              Math.max(item.startMin + NODE_BUFFER_MIN, DAY_END_MIN),
            )
          : Math.min(MINUTES_PER_DAY, endAbs + NODE_BUFFER_MIN);
      intervals.push([
        Math.max(0, item.startMin - NODE_BUFFER_MIN),
        intervalEnd,
      ]);
      // The day the item finally ends, its end minute gets a small live
      // window (if that day is in the trip window) so an early arrival —
      // an overnight flight landing 06:10, say — sits on real, labelable
      // time instead of inside a collapsed night band.
      if (endAbs > MINUTES_PER_DAY) {
        const spanDays = Math.ceil(endAbs / MINUTES_PER_DAY);
        const finalDayIndex = item.dayIndex + spanDays - 1;
        if (finalDayIndex < daysMeta.length) {
          const remainder = endAbs - (spanDays - 1) * MINUTES_PER_DAY;
          intervals.push([
            Math.max(0, remainder - NODE_BUFFER_MIN),
            Math.min(MINUTES_PER_DAY, remainder + NODE_BUFFER_MIN),
          ]);
        }
      }
    }
    intervals.sort((a, b) => a[0] - b[0]);
    const merged: Array<[number, number]> = [];
    for (const [s, e] of intervals) {
      const last = merged[merged.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else merged.push([s, e]);
    }
    const out: TimelineSegment[] = [];
    let yCursor = 0;
    let cursorMin = 0;
    const pushLive = (s: number, e: number) => {
      if (e - s <= 0) return;
      const liveH = (e - s) * effectivePxPerMin;
      out.push({ type: "live", startMin: s, endMin: e, yStart: yCursor, yEnd: yCursor + liveH });
      yCursor += liveH;
    };
    const pushElide = (s: number, e: number) => {
      if (e - s <= 0) return;
      out.push({ type: "elide", startMin: s, endMin: e, yStart: yCursor, yEnd: yCursor + ELIDE_BAND_PX });
      yCursor += ELIDE_BAND_PX;
    };
    // A shoulder (outside the active-day window) elides when it's long enough;
    // short dead gaps stay live so we don't collapse trivial ones.
    const pushShoulder = (s: number, e: number) => {
      if (e - s <= 0) return;
      if (e - s > ELIDE_THRESHOLD_MIN) pushElide(s, e);
      else pushLive(s, e);
    };
    // Split an empty gap into leading-night shoulder, live daytime core, and
    // trailing-night shoulder. The daytime core is ALWAYS live (never elided)
    // so open afternoons keep their full, droppable height.
    const pushGap = (s: number, e: number) => {
      if (e - s <= 0) return;
      const dayS = Math.max(s, DAY_START_MIN);
      const dayE = Math.min(e, DAY_END_MIN);
      if (dayE <= dayS) {
        // Gap lies entirely outside the active-day window.
        pushShoulder(s, e);
        return;
      }
      pushShoulder(s, dayS); // leading night shoulder, if any
      pushLive(dayS, dayE); // daytime core — full height, droppable
      pushShoulder(dayE, e); // trailing night/evening shoulder, if any
    };
    for (const [s, e] of merged) {
      pushGap(cursorMin, s);
      pushLive(s, e);
      cursorMin = e;
    }
    pushGap(cursorMin, MINUTES_PER_DAY);
    return out;
  })();

  // Day column x positions — one column per day. Width grows with lane count
  // so a day with two side-by-side cards reserves room for both.
  const days: DayLayout[] = [];
  let cursorX = TIME_GUTTER + PAD_X;
  for (const dm of daysMeta) {
    const dayIndex = dayIndexByDate.get(dm.date) ?? 0;
    const laneCount = dayLaneCount.get(dm.date) ?? 1;
    const lanesWidth = laneCount * laneWidth + (laneCount - 1) * LANE_GAP;
    const columnWidth = lanesWidth + NIGHT_BAR_GAP + NIGHT_BAR_WIDTH;
    days.push({
      date: dm.date,
      dayIndex,
      columnX: cursorX,
      columnWidth,
      label: dm.label,
      weather_emoji: dm.weather_emoji,
    });
    cursorX += columnWidth + COL_GAP;
  }
  const totalWidth = cursorX + PAD_X;

  // Assemble PositionedHNodes. Each card's y is just `mapMinuteToY(snapped
  // start)`; no stretch-injection needed because the slot is already pre-
  // sized to fit the tallest card that lands there.
  const positions = new Map<string, PositionedHNode>();
  for (const item of items) {
    const dayLayout = days[item.dayIndex];
    if (!dayLayout) continue;
    const baseX = dayLayout.columnX;
    const lane = laneByNode.get(item.node.id) ?? 0;

    let x: number;
    let w: number;
    let y: number;
    let barH: number;

    if (item.isNightBar) {
      x = baseX + dayLayout.columnWidth - NIGHT_BAR_WIDTH;
      w = NIGHT_BAR_WIDTH;
      y = mapMinuteToY(item.startMin, segments);
      const totalSegHeight = segments.reduce(
        (m, s) => Math.max(m, s.yEnd),
        0,
      );
      barH = Math.max(item.cardH, totalSegHeight - y);
    } else {
      x = baseX + lane * (laneWidth + LANE_GAP);
      w = laneWidth;
      y = mapMinuteToY(item.startMin, segments);
      // Duration bar y-span: how tall the event reads on this non-linear
      // axis. May extend well past the card body when an event covers many
      // (mostly-empty) slots — that's the visual cue the user wanted back:
      // a card's footprint shrinks to its content, but the timeline still
      // shows how long the event actually runs.
      const endMin = Math.min(MINUTES_PER_DAY, item.startMin + item.durationMin);
      const yEnd = mapMinuteToY(endMin, segments);
      barH = Math.max(0, yEnd - y);
    }

    const positioned: PositionedHNode = {
      node: item.node,
      dayKey: item.dayKey,
      dayIndex: item.dayIndex,
      lane,
      x,
      y,
      w,
      cardH: item.cardH,
      barH,
      compact: item.compact,
    };
    if (item.isNightBar) positioned.nightBar = true;
    const group = altGroupByNode.get(item.node.id);
    if (group) {
      positioned.altGroup = group;
      const members = altGroups.get(group);
      if (members) positioned.altGroupMembers = members;
    }
    positions.set(item.node.id, positioned);
  }

  // Continuation spans: a multi-day item paints a presence onto every later
  // day it covers (that exists in the trip window). These don't take a lane —
  // they render as a gutter bar plus a small chip — so a card scheduled on a
  // covered day still gets lane 0.
  const continuations: ContinuationSpan[] = [];
  for (const item of items) {
    if (item.isNightBar) continue;
    const endAbs = item.startMin + item.durationMin;
    if (endAbs <= MINUTES_PER_DAY) continue;
    const spanDays = Math.ceil(endAbs / MINUTES_PER_DAY);
    for (let k = 1; k * MINUTES_PER_DAY < endAbs; k++) {
      const dayLayout = days[item.dayIndex + k];
      if (!dayLayout) break; // runs past the trip window — nothing to paint
      const endMin = Math.min(MINUTES_PER_DAY, endAbs - k * MINUTES_PER_DAY);
      const y = mapMinuteToY(0, segments);
      const yEnd = mapMinuteToY(endMin, segments);
      continuations.push({
        node: item.node,
        dayKey: dayLayout.date,
        dayIndex: dayLayout.dayIndex,
        x: dayLayout.columnX,
        w: laneWidth,
        y,
        barH: Math.max(0, yEnd - y),
        endMin,
        isFinal: k === spanDays - 1,
        dayOfSpan: k + 1,
        spanDays,
      });
    }
  }

  // Subgraph beats: each packaged experience's day-by-day children laid onto
  // the timeline as chips that ride the parent's start-finish line (its own
  // duration bar on day 1, its continuation bars on later days). A scheduled
  // child (carries `starts_at`) sits at its real local time and day; an
  // unscheduled one is derived from `subgraph_day.index` — day 1 rides the
  // parent's start (represented by the parent card, so it's skipped), later
  // days step forward to the morning. Never a card/lane of its own.
  const childrenByParent = subgraphChildrenByParent(nodes);
  const subgraphBeats: SubgraphBeat[] = [];
  for (const item of items) {
    if (item.isNightBar) continue;
    const kids = childrenByParent.get(item.node.id);
    if (!kids || kids.length === 0) continue;
    kids.forEach((child, i) => {
      const cm = getHMeta(child);
      const dm = subgraphDayMeta(child);
      let beatDayIndex: number;
      let beatMin: number;
      let scheduled: boolean;
      if (cm.start_time) {
        // Scheduled leg — place at its own local wall-clock (the trip spans
        // tzs, so resolve the offset from the child's own string).
        const ctz = offsetHoursOr(cm.start_time, tzOffsetHours);
        const cDayIndex = dayIndexByDate.get(tzDayKey(cm.start_time, ctz));
        if (cDayIndex === undefined) return; // outside the trip window
        beatDayIndex = cDayIndex;
        beatMin = snapMinute(localMinuteOfDay(cm.start_time, ctz));
        scheduled = true;
      } else {
        const idx = dm.index ?? i + 1;
        // Day 1 is the parent card itself — no separate beat for it.
        if (idx <= 1) return;
        beatDayIndex = item.dayIndex + (idx - 1);
        // An authored beat carries its own clock within the day (`hhmm`); a
        // plain day child starts the morning — same rule as the Journal's
        // `deriveJourneyBeats`, so the two views agree.
        beatMin = dm.hhmm ? snapMinute(hhmmToMinute(dm.hhmm)) : BEAT_MORNING_MIN;
        scheduled = false;
      }
      const dayLayout = days[beatDayIndex];
      if (!dayLayout) return; // runs past the trip window — nothing to paint
      const hours = dm.hours;
      // Enriched child: wear the parent's imagery (like the Journal's beats)
      // and carry the beat's resolved placement as the card's own clock, so the
      // glance card renders a photo + a true start time / duration. The offset
      // (the parent's own, else the trip's) makes the wall time exact for every
      // reader — offset-less strings drift by browser-vs-trip zone.
      const beatSuffix = offsetSuffixOf(getHMeta(item.node).start_time ?? "", tzOffsetHours);
      const beatDayIso = `${dayLayout.date}T${formatMinuteOfDay(beatMin)}:00${beatSuffix}`;
      const beatDurationMin =
        typeof dm.duration_minutes === "number" && dm.duration_minutes > 0
          ? dm.duration_minutes
          : typeof hours === "number" && hours > 0
            ? Math.round(hours * 60)
            : undefined;
      const beatImage = beatImageForChild(item.node, child, dm.index ?? i + 1);
      const beatNode: NodeResponse = {
        ...child,
        metadata: {
          ...child.metadata,
          start_time: cm.start_time ?? beatDayIso,
          ...(beatDurationMin !== undefined
            ? { duration_minutes: beatDurationMin }
            : {}),
          ...(beatImage ? { ambient_image: beatImage } : {}),
        },
      };
      subgraphBeats.push({
        parentId: item.node.id,
        childId: child.id,
        title: child.title,
        node: beatNode,
        dayKey: dayLayout.date,
        dayIndex: beatDayIndex,
        x: dayLayout.columnX,
        w: laneWidth,
        y: mapMinuteToY(beatMin, segments),
        startMin: beatMin,
        ...(typeof hours === "number" && hours > 0 ? { hours } : {}),
        scheduled,
      });
    });
  }

  // Total height: max bottom across segments and cards.
  let segHeight = segments.reduce((m, s) => Math.max(m, s.yEnd), 0);
  for (const p of positions.values()) {
    segHeight = Math.max(segHeight, p.y + p.cardH);
  }
  const totalHeight = segHeight + 80;

  // Time markers: hour boundaries across the full day, plus per-card
  // snapped start times so each card has a label next to it. The TimeAxis
  // dedupe handles cases where a card lands on the hour.
  const labelByMinute = new Map<number, { y: number; label: string }>();
  for (let h = 0; h < 24; h++) {
    const min = h * 60;
    labelByMinute.set(min, {
      y: mapMinuteToY(min, segments),
      label: formatMinuteOfDay(min),
    });
  }
  for (const item of items) {
    if (item.isNightBar) continue;
    if (labelByMinute.has(item.startMin)) continue;
    labelByMinute.set(item.startMin, {
      y: mapMinuteToY(item.startMin, segments),
      label: formatMinuteOfDay(item.startMin),
    });
  }
  // A multi-day item's end minute is a real moment (a landing, a return from
  // an expedition) — label it like a start.
  for (const c of continuations) {
    if (!c.isFinal || c.endMin >= MINUTES_PER_DAY) continue;
    if (labelByMinute.has(c.endMin)) continue;
    labelByMinute.set(c.endMin, {
      y: mapMinuteToY(c.endMin, segments),
      label: formatMinuteOfDay(c.endMin),
    });
  }
  const timeMarkers: TimeMarker[] = Array.from(labelByMinute.values()).sort(
    (a, b) => a.y - b.y,
  );

  return {
    positions,
    continuations,
    subgraphBeats,
    segments,
    days,
    totalWidth,
    totalHeight,
    pxPerMinute,
    tzOffsetHours,
    altGroups,
    timeMarkers,
  };
}
