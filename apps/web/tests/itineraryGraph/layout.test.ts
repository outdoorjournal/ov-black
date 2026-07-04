// The horizontal layout must place each node by ITS OWN local wall-clock —
// a trip spans timezones, so a global offset would misplace cross-tz legs.

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import {
  computeHorizontalLayout,
  mapMinuteToY,
  mapYToMinute,
} from "@/app/_components/itinerary-graph/views/horizontal/layout";

function node(id: string, startTime: string): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: { start_time: startTime, duration_minutes: 60 },
  } as NodeResponse;
}

describe("computeHorizontalLayout per-node timezone", () => {
  test("buckets a node into its own local day even with a different global tz", () => {
    // Global tz is +9 (Tokyo), but the LA node carries -07:00 and must land on
    // its local day (the 20th), not be shifted by the global offset.
    const la = node("la", "2024-06-20T23:00:00-07:00");
    const tokyo = node("tokyo", "2024-06-21T08:00:00+09:00");
    const layout = computeHorizontalLayout({
      nodes: [la, tokyo],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 9,
      daysMeta: [
        { date: "2024-06-20", label: "Day 1" },
        { date: "2024-06-21", label: "Day 2" },
      ],
    });
    expect(layout.positions.get("la")?.dayKey).toBe("2024-06-20");
    expect(layout.positions.get("tokyo")?.dayKey).toBe("2024-06-21");
    // And they sit in different day columns (different x).
    const laX = layout.positions.get("la")!.x;
    const tokyoX = layout.positions.get("tokyo")!.x;
    expect(laX).not.toBe(tokyoX);
  });

  test("places a node at its own local minute-of-day (23:00 local, not UTC)", () => {
    // 23:00-07:00 is 06:00Z; with the per-node offset it must read as the 23rd
    // hour locally — i.e. near the bottom of the day, below an 08:00 node.
    const late = node("late", "2024-06-20T23:00:00-07:00");
    const morning = node("morning", "2024-06-20T08:00:00-07:00");
    const layout = computeHorizontalLayout({
      nodes: [late, morning],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: [{ date: "2024-06-20", label: "Day 1" }],
    });
    const lateY = layout.positions.get("late")!.y;
    const morningY = layout.positions.get("morning")!.y;
    expect(lateY).toBeGreaterThan(morningY);
  });
});

describe("computeHorizontalLayout daytime is never elided", () => {
  // A sparse day with a big empty afternoon between two cards must keep that
  // gap as real, droppable time — otherwise an advisor can't place anything in
  // the open afternoon. Overnight/evening dead air still collapses.
  const morning = node("morning", "2024-06-20T09:00:00Z"); // 09:00
  const afternoon = node("afternoon", "2024-06-20T16:00:00Z"); // 16:00, ~6h gap
  const layout = computeHorizontalLayout({
    nodes: [morning, afternoon],
    edges: [],
    pxPerMinute: 1.2,
    tzOffsetHours: 0,
    daysMeta: [{ date: "2024-06-20", label: "Day 1" }],
  });

  test("the empty afternoon between two cards stays a live segment", () => {
    // 13:00 (780) sits in the empty gap between the 09:00 and 16:00 cards.
    const mid = layout.segments.find((s) => 780 >= s.startMin && 780 < s.endMin);
    expect(mid?.type).toBe("live");
  });

  test("a drop into the empty afternoon lands at that time, not a collapsed edge", () => {
    // Round-tripping a mid-gap minute through the y axis must return ~that
    // minute. An elide band would instead snap it to the band's end minute.
    const y = mapMinuteToY(780, layout.segments);
    expect(mapYToMinute(y, layout.segments)).toBeCloseTo(780, 0);
  });

  test("the overnight shoulder still collapses to an elision band", () => {
    expect(layout.segments.some((s) => s.type === "elide")).toBe(true);
  });
});
