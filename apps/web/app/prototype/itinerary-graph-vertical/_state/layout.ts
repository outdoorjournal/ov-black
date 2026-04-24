import type { EdgeResponse, NodeResponse } from "../_lib/types";
import { getVerticalMeta } from "../_lib/types";
import {
  minutesSince,
  startOfDayIso,
  tzDayKey,
} from "../_lib/time";

export const CARD_WIDTH = 300;
export const LANE_WIDTH = 320;
export const LEFT_GUTTER = 16;
export const CARD_HEIGHT = 132;
export const NIGHT_BAR_WIDTH = 10;
export const NIGHT_BAR_GAP = 6;

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

export interface LayoutResultV {
  positions: Map<string, PositionedVNode>;
  days: Array<{ date: string; y: number; height: number }>;
  totalHeight: number;
  pxPerMinute: number;
  windowStart: string;
  altGroups: Map<string, string[]>;
}

interface LayoutArgs {
  nodes: NodeResponse[];
  edges: EdgeResponse[];
  pxPerMinute: number;
  windowStart: string;
  windowEnd: string;
  tzOffsetHours: number;
  daysMeta: Array<{ date: string }>;
}

export function computeVerticalLayout(args: LayoutArgs): LayoutResultV {
  const { nodes, edges, pxPerMinute, windowStart, tzOffsetHours, daysMeta } = args;

  const positions = new Map<string, PositionedVNode>();

  // Build alt groups from metadata and edges.
  const altGroupByNode = new Map<string, string>();
  for (const n of nodes) {
    const meta = getVerticalMeta(n);
    if (meta.alt_group) altGroupByNode.set(n.id, meta.alt_group);
  }
  // Also treat alternative_to edges as implicit grouping — canonical's id becomes group.
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

  // Day Y positions — use windowStart as day 0.
  const days = daysMeta.map((d) => {
    const dayStart = startOfDayIso(d.date, tzOffsetHours);
    const y = Math.max(0, minutesSince(windowStart, dayStart) * pxPerMinute);
    return { date: d.date, y, height: 24 * 60 * pxPerMinute };
  });

  // Buckets of primary lane occupancy by day to auto-lane concurrent non-alt primaries.
  // Very simple sweep: keep track of lane end times; a lane is "free" if its last endY < new startY - eps.
  const laneEndYByDay = new Map<string, number[]>();

  // Determine lane assignment for each node, grouped by day (tz-based).
  // Sort nodes by start_time ascending.
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
    const y = minutesSince(windowStart, start) * pxPerMinute;
    const dur = typeof meta.duration_minutes === "number" ? meta.duration_minutes : 30;
    const cardH = CARD_HEIGHT;
    const barH = Math.max(cardH, dur * pxPerMinute);

    const group = altGroupByNode.get(node.id);
    let lane = 0;

    if (group) {
      // Lane among group members (ordered by their appearance).
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
      // Sweep-based lane assignment among non-alt nodes per day.
      const endYs = laneEndYByDay.get(dayKey) ?? [];
      const PAD = 4;
      let assigned = -1;
      for (let i = 0; i < endYs.length; i++) {
        const endY = endYs[i] ?? 0;
        if (endY <= y - PAD) {
          assigned = i;
          break;
        }
      }
      if (assigned === -1) {
        assigned = endYs.length;
        endYs.push(0);
      }
      endYs[assigned] = y + Math.max(cardH, dur * pxPerMinute) + PAD;
      laneEndYByDay.set(dayKey, endYs);
      lane = assigned;
    }

    const isNightBar = Boolean(meta.night_bar);
    // Night bar overrides lane — pin to lane -1 on the left rail.
    const effLane = isNightBar ? -1 : lane;
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

  let totalHeight = 0;
  for (const p of positions.values()) {
    totalHeight = Math.max(totalHeight, p.y + p.barH);
  }
  // Pad bottom so last cards have breathing room.
  totalHeight += 240;

  return {
    positions,
    days,
    totalHeight,
    pxPerMinute,
    windowStart,
    altGroups,
  };
}
