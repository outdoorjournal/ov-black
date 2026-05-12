// Horizontal-layout math.
//
// Big idea: each day is its own column laid out left-to-right. All day columns
// share a single y axis whose unit is *minute of day* (0..1440), so 09:00 in
// day 1 sits at exactly the same y as 09:00 in day 8 — you can scan
// horizontally to compare "what was I doing at 10am on each day" and the
// shared sun gradient + weather strip on the left labels them once.
//
// Strategy: **snap + min-row-height** (vs. the earlier "live/elide + stretches"
// approach).
//
//   1. Every card's start_time is rounded to a `SNAP_SLOT_MIN` slot (default
//      15). Lane assignment + y placement work off the snapped value.
//
//   2. The global y axis is a sequence of slot segments. Each occupied slot
//      (any day, any lane has a card there) gets a row whose height is
//      max(pxPerSlot, tallest card-in-this-slot + padding). Same-day-different-
//      lane cards never push each other vertically (they sit side-by-side);
//      same-slot cards across days share the slot's height so they stay aligned.
//
//   3. Empty slots between two occupied slots stay "live" if the gap is short,
//      and collapse to a fixed elision band if it exceeds `ELIDE_THRESHOLD_MIN`.
//      This preserves the current prototype's compact feel for overnight gaps
//      while killing the stretch-injection loop that the earlier algorithm
//      needed when card heights exceeded the time gap between starts.
//
// Night bars (overnight sleep) don't take card-width and don't enter slot
// height calculations; they render as a thin colored strip pinned to the
// right edge of each day column from local-21:00 to the column's bottom.

import type { EdgeResponse, NodeResponse } from "../_lib/types";
import { getHMeta } from "../_lib/types";
import {
  MINUTES_PER_DAY,
  formatMinuteOfDay,
  localMinuteOfDay,
  tzDayKey,
} from "../_lib/time";

export const TIME_GUTTER = 96;
// PAD_X reserves space for the first day's duration-bar gutter; otherwise the
// 16px bar at xOf(p) - 20 would overhang the canvas's left edge.
export const PAD_X = 24;
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

// Snap grid. Start times round to the nearest `SNAP_SLOT_MIN` minutes; the
// axis y is built one slot at a time. `MIN_SLOT_PX` is the floor for an
// empty/short slot at low zoom so the axis still reads as time even when
// pxPerMinute is tiny.
export const SNAP_SLOT_MIN = 15;
export const MIN_SLOT_PX = 6;

// Empty runs longer than this collapse to a fixed-height elision band.
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
  }

  const items: Item[] = [];
  for (const n of nodes) {
    const m = getHMeta(n);
    if (!m.start_time) continue;
    const dayKey = tzDayKey(m.start_time, tzOffsetHours);
    const dayIndex = dayIndexByDate.get(dayKey);
    if (dayIndex === undefined) continue;
    const rawStartMin = localMinuteOfDay(m.start_time, tzOffsetHours);
    const isNightBar = Boolean(m.night_bar);
    // Night bars aren't snapped: they pin to the column edge and don't
    // contribute to slot height; snapping them would just shift their top
    // edge for no visual benefit.
    const startMin = isNightBar ? rawStartMin : snapMinute(rawStartMin);
    const durationMin =
      typeof m.duration_minutes === "number" ? m.duration_minutes : 30;
    const measured = cardHeights?.get(n.id);
    const cardH =
      typeof measured === "number" && measured > 0 ? measured : CARD_FALLBACK_H;
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

  // Slot → required height (max card height + pad across all days/lanes that
  // place a card at this snapped minute). Excluding the dragged source keeps
  // its old slot from holding the row open after it's been picked up.
  const pxPerSlot = Math.max(MIN_SLOT_PX, pxPerMinute * SNAP_SLOT_MIN);
  const slotRequiredH = new Map<number, number>();
  for (const item of items) {
    if (item.isNightBar) continue;
    if (excludeNodeId && item.node.id === excludeNodeId) continue;
    const required = item.cardH + VERTICAL_PAD;
    const cur = slotRequiredH.get(item.startMin) ?? 0;
    if (required > cur) slotRequiredH.set(item.startMin, required);
  }

  // Build segments slot-by-slot across the full 0..1440 day. Occupied slots
  // get their required height; runs of empty slots stay live if short and
  // collapse to an elision band when long.
  const segments: TimelineSegment[] = [];
  {
    let yCursor = 0;
    let emptyStart: number | null = null;

    const flushEmpty = (untilMin: number) => {
      if (emptyStart === null) return;
      const span = untilMin - emptyStart;
      if (span <= 0) {
        emptyStart = null;
        return;
      }
      if (span > ELIDE_THRESHOLD_MIN) {
        segments.push({
          type: "elide",
          startMin: emptyStart,
          endMin: untilMin,
          yStart: yCursor,
          yEnd: yCursor + ELIDE_BAND_PX,
        });
        yCursor += ELIDE_BAND_PX;
      } else {
        const liveH = (span / SNAP_SLOT_MIN) * pxPerSlot;
        segments.push({
          type: "live",
          startMin: emptyStart,
          endMin: untilMin,
          yStart: yCursor,
          yEnd: yCursor + liveH,
        });
        yCursor += liveH;
      }
      emptyStart = null;
    };

    for (let slot = 0; slot < MINUTES_PER_DAY; slot += SNAP_SLOT_MIN) {
      const required = slotRequiredH.get(slot);
      if (required !== undefined) {
        flushEmpty(slot);
        const h = Math.max(pxPerSlot, required);
        segments.push({
          type: "live",
          startMin: slot,
          endMin: slot + SNAP_SLOT_MIN,
          yStart: yCursor,
          yEnd: yCursor + h,
        });
        yCursor += h;
      } else {
        if (emptyStart === null) emptyStart = slot;
      }
    }
    flushEmpty(MINUTES_PER_DAY);
  }

  // Day column x positions — one column per day. Width grows with lane count
  // so a day with two side-by-side cards reserves room for both.
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
      x = baseX + lane * (LANE_WIDTH + LANE_GAP);
      w = LANE_WIDTH;
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

  // Total height: max bottom across segments and cards.
  let segHeight = segments.reduce((m, s) => Math.max(m, s.yEnd), 0);
  for (const p of positions.values()) {
    segHeight = Math.max(segHeight, p.y + p.cardH);
  }
  const totalHeight = segHeight + 80;

  // Time markers: one per occupied snapped slot, plus hour boundaries that
  // fall inside live segments and aren't already covered. Cards anchor to
  // their snapped slot's top y, so the label sits exactly at the card row.
  const labelByMinute = new Map<number, { y: number; label: string }>();
  for (const slot of slotRequiredH.keys()) {
    const y = mapMinuteToY(slot, segments);
    labelByMinute.set(slot, { y, label: formatMinuteOfDay(slot) });
  }
  for (let h = 0; h < 24; h++) {
    const min = h * 60;
    if (labelByMinute.has(min)) continue;
    const live = segments.some(
      (s) => s.startMin <= min && min < s.endMin && s.type === "live",
    );
    if (!live) continue;
    labelByMinute.set(min, {
      y: mapMinuteToY(min, segments),
      label: formatMinuteOfDay(min),
    });
  }
  const timeMarkers: TimeMarker[] = Array.from(labelByMinute.values()).sort(
    (a, b) => a.y - b.y,
  );

  return {
    positions,
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
