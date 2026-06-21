import type { EdgeResponse, NodeResponse } from "@/app/_components/itinerary-graph/model/types";
import { getVerticalMeta } from "@/app/_components/itinerary-graph/model/types";
import {
  formatClock,
  minutesBetween,
  minutesSince,
  startOfDayIso,
  tzDayKey,
} from "@/app/_components/itinerary-graph/model/time";

export const CARD_WIDTH = 300;
export const LANE_WIDTH = 320;
export const LEFT_GUTTER = 16;
export const CARD_HEIGHT = 132;
export const NIGHT_BAR_WIDTH = 10;
export const NIGHT_BAR_GAP = 6;

// How long a node "owns" for elision purposes. Anything beyond this in the
// same node is collapsible (so a 9h night bar doesn't keep 9h of pixels alive).
const NODE_OWN_MAX_MIN = 75;
const NODE_BUFFER_MIN = 18;
// Gaps shorter than this stay live; longer gaps collapse into a fixed band.
const ELIDE_THRESHOLD_MIN = 90;
const ELIDE_BAND_PX = 56;

export interface TimelineSegment {
  type: "live" | "elide";
  startMin: number;
  endMin: number;
  yStart: number;
  yEnd: number;
}

export interface PositionedVNode {
  node: NodeResponse;
  x: number;
  y: number;
  w: number;
  cardH: number;
  barH: number;
  lane: number;
  altGroup?: string;
  altGroupMembers?: string[];
  nightBar?: boolean;
  dayKey: string;
}

export interface TimeMarker {
  y: number;
  label: string;
  count: number;
}

export interface LayoutResultV {
  positions: Map<string, PositionedVNode>;
  days: Array<{ date: string; y: number; height: number }>;
  segments: TimelineSegment[];
  totalHeight: number;
  pxPerMinute: number;
  windowStart: string;
  tzOffsetHours: number;
  altGroups: Map<string, string[]>;
  timeMarkers: TimeMarker[];
}

interface LayoutArgs {
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pxPerMinute: number;
  windowStart: string;
  windowEnd: string;
  tzOffsetHours: number;
  daysMeta: Array<{ date: string }>;
  // Measured card heights keyed by node id. Falls back to CARD_HEIGHT when a
  // card hasn't reported its rendered height yet (first frame).
  cardHeights?: Map<string, number>;
}

function buildSegments(
  nodes: NodeResponse[],
  pxPerMinute: number,
  windowStart: string,
  windowEnd: string,
): TimelineSegment[] {
  const totalMin = minutesBetween(windowStart, windowEnd);

  const intervals: Array<[number, number]> = [];
  for (const n of nodes) {
    const m = getVerticalMeta(n);
    if (!m.start_time) continue;
    const startMin = minutesSince(windowStart, m.start_time);
    const dur = typeof m.duration_minutes === "number" ? m.duration_minutes : 30;
    const ownDur = Math.min(dur, NODE_OWN_MAX_MIN);
    intervals.push([
      Math.max(0, startMin - NODE_BUFFER_MIN),
      Math.min(totalMin, startMin + ownDur + NODE_BUFFER_MIN),
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
  pushGap(cursorMin, totalMin);

  return segments;
}

export function mapMinuteToY(min: number, segments: TimelineSegment[]): number {
  for (const seg of segments) {
    if (min < seg.startMin) return seg.yStart;
    if (min <= seg.endMin) {
      const range = seg.endMin - seg.startMin || 1;
      const t = (min - seg.startMin) / range;
      return seg.yStart + t * (seg.yEnd - seg.yStart);
    }
  }
  const last = segments[segments.length - 1];
  return last ? last.yEnd : 0;
}

export function computeVerticalLayout(args: LayoutArgs): LayoutResultV {
  const {
    nodes,
    edges,
    pxPerMinute,
    windowStart,
    windowEnd,
    tzOffsetHours,
    daysMeta,
    cardHeights,
  } = args;

  const positions = new Map<string, PositionedVNode>();

  // Alt groups (metadata + alternative_to edges) — same as before.
  const altGroupByNode = new Map<string, string>();
  for (const n of nodes) {
    const meta = getVerticalMeta(n);
    if (meta.alt_group) altGroupByNode.set(n.id, meta.alt_group);
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

  const segments = buildSegments(nodes, pxPerMinute, windowStart, windowEnd);

  // Lane assignment is purely time-based: two events share lane 0 unless their
  // [start, start+duration) intervals genuinely overlap. Visual card height is
  // ignored here — that's a zoom/rendering concern, not a scheduling one.
  const laneEndMinByDay = new Map<string, number[]>();

  // Stretch points are local injections of extra pixels at specific minute
  // boundaries. They make the timeline piecewise-linear (constant pxPerMinute
  // within a stretch-free region, with a one-time jump at each stretch atMin)
  // so two cards in the same lane never visually overlap even when their time
  // gap is shorter than the card height at the current zoom.
  const stretchPoints: Array<{ atMin: number; px: number }> = [];
  const stretchBefore = (min: number): number => {
    let total = 0;
    for (const s of stretchPoints) {
      if (s.atMin <= min) total += s.px;
    }
    return total;
  };
  const laneLastBottom = new Map<number, number>();
  const VERTICAL_PAD = 8;

  const withTimes = nodes
    .map((n) => {
      const meta = getVerticalMeta(n);
      const start = meta.start_time ?? windowStart;
      return { node: n, meta, start };
    })
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  for (const entry of withTimes) {
    const { node, meta, start } = entry;
    const dayKey = tzDayKey(start, tzOffsetHours);
    const startMin = minutesSince(windowStart, start);
    const dur = typeof meta.duration_minutes === "number" ? meta.duration_minutes : 30;
    const cardH = CARD_HEIGHT;

    const group = altGroupByNode.get(node.id);
    let lane = 0;

    if (group) {
      const members = altGroups.get(group) ?? [];
      const orderedMembers = members
        .map((id) => nodes.find((n) => n.id === id))
        .filter((n): n is NodeResponse => Boolean(n))
        .sort((a, b) => {
          const sa = new Date(getVerticalMeta(a).start_time ?? windowStart).getTime();
          const sb = new Date(getVerticalMeta(b).start_time ?? windowStart).getTime();
          return sa - sb;
        });
      lane = orderedMembers.findIndex((n) => n.id === node.id);
      if (lane < 0) lane = 0;
    } else {
      const eventEndMin = startMin + dur;
      const laneEndMins = laneEndMinByDay.get(dayKey) ?? [];
      let assigned = -1;
      for (let i = 0; i < laneEndMins.length; i++) {
        const endMin = laneEndMins[i] ?? 0;
        if (endMin <= startMin) {
          assigned = i;
          break;
        }
      }
      if (assigned === -1) {
        assigned = laneEndMins.length;
        laneEndMins.push(0);
      }
      laneEndMins[assigned] = eventEndMin;
      laneEndMinByDay.set(dayKey, laneEndMins);
      lane = assigned;
    }

    const isNightBar = Boolean(meta.night_bar);
    const effLane = isNightBar ? -1 : lane;

    // Measured height beats the static CARD_HEIGHT estimate — experience cards
    // with cover images can be ~200px while a transit card is ~80px. Without
    // measurement, the static estimate undershoots and adjacent cards overlap.
    const measuredH = cardHeights?.get(node.id);
    const effectiveH = typeof measuredH === "number" && measuredH > 0
      ? measuredH
      : cardH;

    let y = mapMinuteToY(startMin, segments) + stretchBefore(startMin);
    if (!isNightBar) {
      const lastBottom = laneLastBottom.get(effLane) ?? Number.NEGATIVE_INFINITY;
      const minY = lastBottom + VERTICAL_PAD;
      if (y < minY) {
        const extra = minY - y;
        stretchPoints.push({ atMin: startMin, px: extra });
        y += extra;
      }
      laneLastBottom.set(effLane, y + effectiveH);
    }

    const yEnd = mapMinuteToY(startMin + dur, segments) + stretchBefore(startMin + dur);
    const barH = Math.max(cardH, yEnd - y);

    const x = isNightBar
      ? LEFT_GUTTER
      : LEFT_GUTTER + NIGHT_BAR_WIDTH + NIGHT_BAR_GAP + effLane * LANE_WIDTH;

    const positioned: PositionedVNode = {
      node,
      x,
      y,
      w: isNightBar ? NIGHT_BAR_WIDTH : CARD_WIDTH,
      cardH,
      barH,
      lane: effLane,
      dayKey,
    };
    if (group) {
      positioned.altGroup = group;
      const members = altGroups.get(group);
      if (members) positioned.altGroupMembers = members;
    }
    if (isNightBar) positioned.nightBar = true;
    positions.set(node.id, positioned);
  }

  // Bake stretches into segments so the gradient + tick layer + mapMinuteToY
  // (used by ghost proposals) all see the same stretched mapping. Each segment
  // pushes its boundaries by the cumulative stretch up to that minute; stretches
  // landing inside a segment get absorbed into its [yStart, yEnd] span (the
  // gradient interpolates linearly through them, which is fine for soft sun
  // tints).
  for (const seg of segments) {
    seg.yStart += stretchBefore(seg.startMin);
    seg.yEnd += stretchBefore(seg.endMin);
  }

  // Days computed against stretched segments so day tiles ride the same axis.
  const days = daysMeta.map((d) => {
    const dayStartIso = startOfDayIso(d.date, tzOffsetHours);
    const dayStartMin = Math.max(0, minutesSince(windowStart, dayStartIso));
    const dayEndMin = dayStartMin + 24 * 60;
    const yStart = mapMinuteToY(dayStartMin, segments);
    const yEnd = mapMinuteToY(dayEndMin, segments);
    return { date: d.date, y: yStart, height: Math.max(0, yEnd - yStart) };
  });

  let totalHeight = segments.reduce((m, s) => Math.max(m, s.yEnd), 0);
  for (const p of positions.values()) {
    totalHeight = Math.max(totalHeight, p.y + p.barH);
  }
  totalHeight += 240;

  const markerMap = new Map<string, TimeMarker>();
  for (const p of positions.values()) {
    if (p.nightBar) continue;
    const startIso = getVerticalMeta(p.node).start_time;
    if (!startIso) continue;
    const label = formatClock(startIso, tzOffsetHours);
    const existing = markerMap.get(label);
    if (existing) {
      existing.count += 1;
      existing.y = Math.min(existing.y, p.y);
    } else {
      markerMap.set(label, { y: p.y, label, count: 1 });
    }
  }
  const timeMarkers = Array.from(markerMap.values()).sort((a, b) => a.y - b.y);

  return {
    positions,
    days,
    segments,
    totalHeight,
    pxPerMinute,
    windowStart,
    tzOffsetHours,
    altGroups,
    timeMarkers,
  };
}
