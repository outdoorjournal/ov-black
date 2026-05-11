// Horizontal-layout math.
//
// Big idea: each day is its own column laid out left-to-right. All day columns
// share a single y axis whose unit is *minute of day* (0..1440), so 09:00 in
// day 1 sits at exactly the same y as 09:00 in day 8 — you can scan
// horizontally to compare "what was I doing at 10am on each day" and the
// shared sun gradient + weather strip on the left labels them once.
//
// Two pieces of math fall out of that:
//
//   1. Piecewise time→y, computed once globally. We collect the union of
//      "live" minute-of-day intervals across *all* days (any day with a card
//      between 09:30 and 10:00 makes that interval live). Dead intervals (no
//      day uses them) collapse to a fixed-height elision band. Live intervals
//      stretch by `pxPerMinute`.
//
//   2. **Stretches, not lanes.** Each day is a single fixed-width column. If
//      two cards in the same day would visually overlap (because card heights
//      exceed the time gap between starts at the current zoom), we *push the
//      later card down* by injecting a one-time pixel offset at that minute
//      boundary. The offset feeds back into the global time→y so all days
//      stay aligned: a stretch needed by day 2's 09:00→10:00 also pushes
//      day 8's 10:30 card down. Cards never overlap; the timeline simply
//      grows taller. This mirrors the vertical prototype's behavior.
//
// Night bars (overnight sleep) don't take card-width and don't enter the
// stretch loop; they render as a thin colored strip pinned to the right edge
// of each day column from local-21:00 to the column's bottom.

import type { EdgeResponse, NodeResponse } from "../_lib/types";
import { getHMeta } from "../_lib/types";
import {
  MINUTES_PER_DAY,
  formatMinuteOfDay,
  localMinuteOfDay,
  tzDayKey,
} from "../_lib/time";

export const TIME_GUTTER = 96;
export const PAD_X = 16;
export const PAD_TOP = 12;
export const DAY_HEADER_HEIGHT = 64;
// Matches CardShell glance width (`w-[260px]`) in /prototype/cards so the
// focused/dragging chrome wraps the visible card edge exactly. `LANE_WIDTH`
// is the in-day side-by-side slot width — currently the same as the legacy
// `COL_WIDTH` because a day with one lane should render identically to the
// pre-lane layout.
export const LANE_WIDTH = 260;
export const LANE_GAP = 12;
export const COL_WIDTH = LANE_WIDTH;
export const COL_GAP = 20;
export const NIGHT_BAR_WIDTH = 6;
export const NIGHT_BAR_GAP = 4;
export const CARD_FALLBACK_H = 132;
export const VERTICAL_PAD = 8;

// How long a node "owns" minutes for the elision computation. A 9-hour night
// bar shouldn't keep 9h of pixels live — only the first ~75 min get padded.
const NODE_OWN_MAX_MIN = 75;
const NODE_BUFFER_MIN = 18;
// Gaps shorter than this stay live (so 30m of context around an event still
// shows). Longer gaps elide into a fixed band.
const ELIDE_THRESHOLD_MIN = 90;
const ELIDE_BAND_PX = 56;

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

export interface TimeMarker {
  y: number;
  label: string;
}

export interface HLayoutResult {
  positions: Map<string, PositionedHNode>;
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

// Build the global minute-of-day live-interval union from every non-night-bar
// node, regardless of which day it belongs to. Then translate into segments
// (live ∪ elided) along the y axis.
function buildSegments(
  nodes: NodeResponse[],
  pxPerMinute: number,
  tzOffsetHours: number,
): TimelineSegment[] {
  const intervals: Array<[number, number]> = [];
  for (const n of nodes) {
    const m = getHMeta(n);
    if (!m.start_time) continue;
    if (m.night_bar) continue;
    const startMin = localMinuteOfDay(m.start_time, tzOffsetHours);
    const dur = typeof m.duration_minutes === "number" ? m.duration_minutes : 30;
    const ownDur = Math.min(dur, NODE_OWN_MAX_MIN);
    intervals.push([
      Math.max(0, startMin - NODE_BUFFER_MIN),
      Math.min(MINUTES_PER_DAY, startMin + ownDur + NODE_BUFFER_MIN),
    ]);
  }
  intervals.sort((a, b) => a[0] - b[0]);

  const merged: Array<[number, number]> = [];
  for (const [s, e] of intervals) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1]) {
      last[1] = Math.max(last[1], e);
    } else {
      merged.push([s, e]);
    }
  }

  const segments: TimelineSegment[] = [];
  let yCursor = 0;
  let cursorMin = 0;

  const pushGap = (s: number, e: number) => {
    const gap = e - s;
    if (gap <= 0) return;
    if (gap > ELIDE_THRESHOLD_MIN) {
      segments.push({
        type: "elide",
        startMin: s,
        endMin: e,
        yStart: yCursor,
        yEnd: yCursor + ELIDE_BAND_PX,
      });
      yCursor += ELIDE_BAND_PX;
    } else {
      segments.push({
        type: "live",
        startMin: s,
        endMin: e,
        yStart: yCursor,
        yEnd: yCursor + gap * pxPerMinute,
      });
      yCursor += gap * pxPerMinute;
    }
  };

  for (const [s, e] of merged) {
    pushGap(cursorMin, s);
    const len = e - s;
    segments.push({
      type: "live",
      startMin: s,
      endMin: e,
      yStart: yCursor,
      yEnd: yCursor + len * pxPerMinute,
    });
    yCursor += len * pxPerMinute;
    cursorMin = e;
  }
  pushGap(cursorMin, MINUTES_PER_DAY);

  return segments;
}

export function mapMinuteToY(min: number, segments: TimelineSegment[]): number {
  // Note the strict `<` on endMin: at a segment boundary (e.g. a stretch
  // split at minute 460 produces two segments [..,460] and [460,..]) we
  // want `min === 460` to fall in the *right* segment so the returned y
  // reflects the post-stretch position. Otherwise cards placed with a
  // step-discontinuity stretch would sit below where the axis thinks they
  // should be.
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

// Inverse of mapMinuteToY — useful for translating a drag's pointer-y back
// into a clock minute so the dragged card can adopt the time it's being
// dropped at. Elide bands collapse onto the band's boundary minute (so a
// drop into a dead gap snaps to the nearest live edge rather than landing
// on an undefined hour).
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

// Split segments at every stretch's atMin so each stretch becomes a real
// segment boundary (a vertical jump in y) rather than a value that gets
// distributed linearly across a segment's interior. After this transform,
// mapMinuteToY agrees exactly with the per-card y values computed during
// the placement loop — no more cards drifting above/below their hour mark.
function applyStretchesToSegments(
  segments: TimelineSegment[],
  stretchPoints: Array<{ atMin: number; px: number }>,
): TimelineSegment[] {
  // Stable-sort by atMin so multiple stretches at the same minute compound
  // in the order they were pushed.
  const sorted = stretchPoints
    .map((s, i) => ({ ...s, _i: i }))
    .sort((a, b) => a.atMin - b.atMin || a._i - b._i);

  let result: TimelineSegment[] = segments.map((s) => ({ ...s }));
  for (const stretch of sorted) {
    const next: TimelineSegment[] = [];
    for (const seg of result) {
      if (stretch.atMin > seg.startMin && stretch.atMin < seg.endMin) {
        // Split: [startMin .. atMin] keeps original y, [atMin .. endMin]
        // shifts by px.
        const t = (stretch.atMin - seg.startMin) / (seg.endMin - seg.startMin);
        const yAt = seg.yStart + t * (seg.yEnd - seg.yStart);
        next.push({ ...seg, endMin: stretch.atMin, yEnd: yAt });
        next.push({
          ...seg,
          startMin: stretch.atMin,
          yStart: yAt + stretch.px,
          yEnd: seg.yEnd + stretch.px,
        });
      } else if (stretch.atMin <= seg.startMin) {
        // Segment lives entirely at or after the stretch — shift it down.
        next.push({
          ...seg,
          yStart: seg.yStart + stretch.px,
          yEnd: seg.yEnd + stretch.px,
        });
      } else {
        // Segment lives entirely before the stretch — leave alone.
        next.push(seg);
      }
    }
    result = next;
  }
  return result;
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

  const segments = buildSegments(nodes, pxPerMinute, tzOffsetHours);

  // Stretches are global (a stretch at minute X pushes everything past X
  // down by `px` in *every* column). Multi-day cards keep their column-wise
  // alignment because all columns share the same time→y function.
  const stretchPoints: Array<{ atMin: number; px: number }> = [];
  const stretchBefore = (min: number): number => {
    let total = 0;
    for (const s of stretchPoints) {
      if (s.atMin <= min) total += s.px;
    }
    return total;
  };

  // Bucket nodes by tz day key. We process items in **global time order**
  // (across all days simultaneously) so that an early-day-2 stretch is
  // visible to a later-day-8 item.
  const dayIndexByDate = new Map<string, number>();
  daysMeta.forEach((d, i) => dayIndexByDate.set(d.date, i));

  interface Item {
    node: NodeResponse;
    meta: ReturnType<typeof getHMeta>;
    dayKey: string;
    dayIndex: number;
    startMin: number;
    cardH: number;
    isNightBar: boolean;
  }

  const items: Item[] = [];
  for (const n of nodes) {
    const m = getHMeta(n);
    if (!m.start_time) continue;
    const dayKey = tzDayKey(m.start_time, tzOffsetHours);
    const dayIndex = dayIndexByDate.get(dayKey);
    if (dayIndex === undefined) continue;
    const startMin = localMinuteOfDay(m.start_time, tzOffsetHours);
    const measured = cardHeights?.get(n.id);
    const cardH =
      typeof measured === "number" && measured > 0 ? measured : CARD_FALLBACK_H;
    items.push({
      node: n,
      meta: m,
      dayKey,
      dayIndex,
      startMin,
      cardH,
      isNightBar: Boolean(m.night_bar),
    });
  }

  // Pre-pass: per-day lane assignment based on time overlap. Cards whose
  // [start, start+duration] intervals collide go to successively higher
  // lanes (rendered side-by-side in the same day column). Night bars do not
  // participate — they live in the column's right-edge strip and never
  // compete with cards for lane room. While a drag is in flight, the
  // dragged source is excluded from lane competition so its old position
  // doesn't push the ghost into a second lane during a same-day reorder.
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
      // Stable sort by startMin (insertion order breaks ties so the original
      // fixture ordering wins when two items literally share a start_time).
      const indexed = dayItems.map((it, i) => ({ it, i }));
      indexed.sort((a, b) =>
        a.it.startMin === b.it.startMin
          ? a.i - b.i
          : a.it.startMin - b.it.startMin,
      );
      // laneEnd[i] = endMin of the latest card placed in lane i so far.
      const laneEnd: number[] = [];
      for (const { it } of indexed) {
        const dur =
          typeof it.meta.duration_minutes === "number"
            ? it.meta.duration_minutes
            : 30;
        const end = it.startMin + dur;
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
    // The dragged source is given lane 0 so it still renders at a sensible
    // x; its stretch / lastBottom contributions are skipped below so other
    // cards behave as if its slot is empty.
    if (excludeNodeId) laneByNode.set(excludeNodeId, 0);
  }

  // Sort items globally by (startMin, dayIndex, lane). Sorting by minute
  // first means stretches injected for day 2's 08:30 are visible to day 5's
  // 09:00 before either has been laid out — keeping the global axis
  // monotone. Tie-breaking by lane lets the same-minute group resolve from
  // the leftmost lane outward.
  items.sort((a, b) => {
    if (a.startMin !== b.startMin) return a.startMin - b.startMin;
    if (a.dayIndex !== b.dayIndex) return a.dayIndex - b.dayIndex;
    return (laneByNode.get(a.node.id) ?? 0) - (laneByNode.get(b.node.id) ?? 0);
  });

  // Per (day,lane) lastBottom tracking. Two cards in different lanes of the
  // same day at the same minute don't need to push each other vertically —
  // they sit side-by-side instead. Only same-lane collisions trigger stretch.
  const laneKey = (dayKey: string, lane: number) => `${dayKey}#${lane}`;
  const dayLastBottom = new Map<string, number>();
  const ys = new Map<string, number>();
  const yBots = new Map<string, number>();

  // Process items in **groups by startMin**, not one-at-a-time. Two items at
  // the same minute (say 15:00 in Day 2 and Day 7) need to share whichever
  // stretch the busier day requires; otherwise the calmer day's card stays
  // at the pre-stretch y while the time axis shows the post-stretch y, and
  // the card visually drifts to the wrong time. We resolve the whole group
  // before moving on so every co-minute card lands on the same y.
  let i = 0;
  while (i < items.length) {
    const startMin = items[i]!.startMin;
    let j = i;
    while (j < items.length && items[j]!.startMin === startMin) j++;
    const group = items.slice(i, j);
    i = j;

    // Night bars don't compete with cards for vertical room.
    const cardGroup = group.filter((g) => !g.isNightBar);
    if (cardGroup.length === 0) continue;

    // Common starting y for the whole group, before any push at this minute.
    // (mapMinuteToY against the still-unstretched `segments` plus all
    // stretches at atMin < startMin — earlier groups have already pushed
    // theirs.)
    const yInitial =
      mapMinuteToY(startMin, segments) + stretchBefore(startMin);

    // Find the max push the group needs to clear its (day, lane) previous
    // card. Same-day siblings in *different* lanes don't push each other —
    // that's what lets a drop sit beside a busy slot instead of below it.
    // We deliberately *don't* exclude the dragged source from stretch
    // math: keeping its lastBottom in place prevents the rest of the day
    // from collapsing upward during drag (which would warp the pointer-y →
    // minute mapping mid-gesture).
    let maxExtra = 0;
    for (const item of cardGroup) {
      const lane = laneByNode.get(item.node.id) ?? 0;
      const key = laneKey(item.dayKey, lane);
      const lastBot = dayLastBottom.get(key) ?? Number.NEGATIVE_INFINITY;
      const minY = lastBot + VERTICAL_PAD;
      const extra = minY - yInitial;
      if (extra > maxExtra) maxExtra = extra;
    }
    if (maxExtra > 0) {
      stretchPoints.push({ atMin: startMin, px: maxExtra });
    }
    const finalY = yInitial + maxExtra;
    for (const item of cardGroup) {
      const lane = laneByNode.get(item.node.id) ?? 0;
      ys.set(item.node.id, finalY);
      yBots.set(item.node.id, finalY + item.cardH);
      dayLastBottom.set(laneKey(item.dayKey, lane), finalY + item.cardH);
    }
  }

  // Materialize the stretches as real segment boundaries (a vertical jump
  // at each `atMin`) rather than spreading them linearly across the segment
  // they land in. This is what keeps cards exactly aligned with their hour
  // marks: a card at 07:40 that pushed +30px sits at the post-stretch y,
  // and the 08:00 hour marker — computed from displaySegments — sits 20
  // minutes of pxPerMinute below that, exactly on the card row right under
  // it. The old "add stretchBefore to seg endpoints" step couldn't deliver
  // this because it interpolated the discontinuity into a slope.
  const displaySegments = applyStretchesToSegments(segments, stretchPoints);
  // Reference stretchBefore here so it's not flagged as unused — it's kept
  // around because card-placement logic depends on it. (The bake step
  // that used to consume it is gone.)
  void stretchBefore;

  // Now compute day column x positions — one column per day. Width grows
  // with lane count so a day with two side-by-side cards reserves room for
  // both. Sparse days keep their original single-lane width.
  const days: DayLayout[] = [];
  let cursorX = TIME_GUTTER + PAD_X;
  for (const dm of daysMeta) {
    const dayIndex = dayIndexByDate.get(dm.date) ?? 0;
    const laneCount = dayLaneCount.get(dm.date) ?? 1;
    const lanesWidth = laneCount * LANE_WIDTH + (laneCount - 1) * LANE_GAP;
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

  // Assemble PositionedHNodes against the now-known column x's. Cards sit
  // at columnX + lane * (LANE_WIDTH + LANE_GAP); night bars pin to the
  // column's right edge regardless of how many lanes are open.
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
      y = mapMinuteToY(item.startMin, displaySegments);
      // Strip from local 21:00 down to the column bottom.
      const totalSegHeight = displaySegments.reduce(
        (m, s) => Math.max(m, s.yEnd),
        0,
      );
      barH = Math.max(item.cardH, totalSegHeight - y);
    } else {
      x = baseX + lane * (LANE_WIDTH + LANE_GAP);
      w = LANE_WIDTH;
      y = ys.get(item.node.id) ?? mapMinuteToY(item.startMin, displaySegments);
      const yBot = yBots.get(item.node.id) ?? y + item.cardH;
      barH = yBot - y;
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

  // Total height: max bottom across cards and (stretched) segments.
  let segHeight = displaySegments.reduce((m, s) => Math.max(m, s.yEnd), 0);
  for (const p of positions.values()) {
    segHeight = Math.max(segHeight, p.y + p.cardH);
  }
  const totalHeight = segHeight + 80;

  // Time markers: one per unique card start-time (HH:MM), placed at the
  // card's actual y. Same idiom the vertical prototype uses — every card
  // has a label *next to it*, so non-uniform stretches between hours never
  // make a card look misplaced relative to its label. Hour boundaries are
  // also added when no card lands on them, so the gutter still reads as a
  // clock when the schedule is sparse.
  const labelByMinute = new Map<number, { y: number; label: string }>();
  for (const item of items) {
    if (item.isNightBar) continue;
    const y = ys.get(item.node.id);
    if (typeof y !== "number") continue;
    const existing = labelByMinute.get(item.startMin);
    if (existing) {
      // Multiple cards at the same minute share one label at the topmost y.
      if (y < existing.y) existing.y = y;
    } else {
      labelByMinute.set(item.startMin, {
        y,
        label: formatMinuteOfDay(item.startMin),
      });
    }
  }
  // Backfill empty hour boundaries inside live original segments.
  for (let h = 0; h < 24; h++) {
    const min = h * 60;
    if (labelByMinute.has(min)) continue;
    const live = segments.some(
      (s) => s.startMin <= min && min <= s.endMin && s.type === "live",
    );
    if (!live) continue;
    labelByMinute.set(min, {
      y: mapMinuteToY(min, displaySegments),
      label: formatMinuteOfDay(min),
    });
  }
  const timeMarkers: TimeMarker[] = Array.from(labelByMinute.values()).sort(
    (a, b) => a.y - b.y,
  );

  return {
    positions,
    segments: displaySegments,
    days,
    totalWidth,
    totalHeight,
    pxPerMinute,
    tzOffsetHours,
    altGroups,
    timeMarkers,
  };
}
