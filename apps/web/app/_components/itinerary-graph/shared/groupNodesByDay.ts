// Bucket itinerary nodes into the trip's day columns. One shared definition of
// "which day does this node belong to" for every surface that groups by day —
// including the trip-spans-timezones rule (each node is placed by its OWN tz
// offset, not the trip default).

import { offsetHoursOr } from "../model/horizontalTime";
import type { NodeResponse } from "../model/horizontalTypes";
import { getHMeta } from "../model/horizontalTypes";

export interface DayGroup {
  /** Local calendar day, YYYY-MM-DD. */
  date: string;
  label: string;
  weather_emoji?: string;
  items: NodeResponse[];
}

/**
 * The local-calendar day key (YYYY-MM-DD) a node falls on, honoring the node's
 * own tz offset (the trip can cross zones), or null when it carries no start.
 */
export function dayKeyForNode(
  node: NodeResponse,
  tzOffsetHours: number,
): string | null {
  const start = getHMeta(node).start_time;
  if (!start) return null;
  const nodeTz = offsetHoursOr(start, tzOffsetHours);
  const ms = new Date(start).getTime() + nodeTz * 3600 * 1000;
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${mo}-${day}`;
}

/**
 * The index of the day column a node belongs to within `daysMeta`, or -1 if it
 * has no start time or falls outside the window. Used to route a freshly
 * proposed card to its day (e.g. "jump to Thu").
 */
export function dayIndexForNode(
  node: NodeResponse,
  daysMeta: Array<{ date: string }>,
  tzOffsetHours: number,
): number {
  const key = dayKeyForNode(node, tzOffsetHours);
  if (!key) return -1;
  return daysMeta.findIndex((d) => d.date === key);
}

/**
 * Group `nodes` into the trip's `daysMeta` columns (preserving day order and
 * labels), sorting each day's items by start time. Nodes with no start_time —
 * or whose day falls outside the window — are dropped.
 */
export function groupNodesByDay(
  nodes: NodeResponse[],
  daysMeta: Array<{ date: string; label: string; weather_emoji?: string }>,
  tzOffsetHours: number,
): DayGroup[] {
  const byDay = new Map<string, NodeResponse[]>();
  for (const n of nodes) {
    const key = dayKeyForNode(n, tzOffsetHours);
    if (!key) continue;
    const arr = byDay.get(key) ?? [];
    arr.push(n);
    byDay.set(key, arr);
  }
  return daysMeta.map((dm) => {
    const items = (byDay.get(dm.date) ?? []).slice().sort((a, b) => {
      const sa = new Date(getHMeta(a).start_time ?? "").getTime();
      const sb = new Date(getHMeta(b).start_time ?? "").getTime();
      return sa - sb;
    });
    return {
      date: dm.date,
      label: dm.label,
      ...(dm.weather_emoji ? { weather_emoji: dm.weather_emoji } : {}),
      items,
    };
  });
}
