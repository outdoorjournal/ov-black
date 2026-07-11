// The horizontal layout must place each node by ITS OWN local wall-clock —
// a trip spans timezones, so a global offset would misplace cross-tz legs.

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import {
  computeHorizontalLayout,
  mapMinuteToY,
  mapYToMinute,
} from "@/app/_components/itinerary-graph/views/horizontal/layout";

function node(
  id: string,
  startTime: string,
  durationMinutes = 60,
  type = "experience",
): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type,
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: { start_time: startTime, duration_minutes: durationMinutes },
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

describe("computeHorizontalLayout multi-day items", () => {
  const days = [
    { date: "2026-09-14", label: "Day 1" },
    { date: "2026-09-15", label: "Day 2" },
    { date: "2026-09-16", label: "Day 3" },
    { date: "2026-09-17", label: "Day 4" },
    { date: "2026-09-18", label: "Day 5" },
    { date: "2026-09-19", label: "Day 6" },
  ];

  test("an overnight flight paints a continuation on the arrival day ending at the arrival minute", () => {
    // Departs 23:00, flies 8h → lands 07:00 the next day.
    const redEye = node("redeye", "2026-09-14T23:00:00Z", 480, "flight");
    const layout = computeHorizontalLayout({
      nodes: [redEye],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: days,
    });
    // The card stays on the departure day…
    expect(layout.positions.get("redeye")?.dayKey).toBe("2026-09-14");
    // …and exactly one continuation lands on the arrival day.
    expect(layout.continuations).toHaveLength(1);
    const cont = layout.continuations[0]!;
    expect(cont.dayKey).toBe("2026-09-15");
    expect(cont.endMin).toBe(7 * 60);
    expect(cont.isFinal).toBe(true);
    expect(cont.spanDays).toBe(2);
    // The continuation bar starts at the top of the day and has real height.
    expect(cont.y).toBe(0);
    expect(cont.barH).toBeGreaterThan(0);
    // The arrival minute gets a time-axis label like any start would.
    expect(layout.timeMarkers.some((m) => m.label === "07:00")).toBe(true);
  });

  test("a 4-day expedition covers every day it spans, final day marked with its end", () => {
    // Starts 08:00 on Day 2, runs 96h → ends 08:00 on Day 6 (5 calendar days).
    const safari = node("safari", "2026-09-15T08:00:00Z", 5760);
    const layout = computeHorizontalLayout({
      nodes: [safari],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: days,
    });
    const conts = layout.continuations;
    expect(conts.map((c) => c.dayKey)).toEqual([
      "2026-09-16",
      "2026-09-17",
      "2026-09-18",
      "2026-09-19",
    ]);
    // Middle days run through midnight; only the last day ends mid-day.
    expect(conts.slice(0, 3).every((c) => !c.isFinal && c.endMin === 1440)).toBe(
      true,
    );
    const last = conts[conts.length - 1]!;
    expect(last.isFinal).toBe(true);
    expect(last.endMin).toBe(8 * 60);
    expect(last.dayOfSpan).toBe(5);
    expect(last.spanDays).toBe(5);
  });

  test("a spanning item does not force the shared night live — elision survives", () => {
    // Without the cap, the safari's [08:00 → midnight] occupancy would make
    // every evening in the trip live and stretch all six columns.
    const safari = node("safari", "2026-09-15T08:00:00Z", 5760);
    const dinner = node("dinner", "2026-09-14T19:00:00Z", 90);
    const layout = computeHorizontalLayout({
      nodes: [safari, dinner],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: days,
    });
    const lateNight = layout.segments.find(
      (s) => s.startMin >= 21 * 60 && s.type === "elide",
    );
    expect(lateNight).toBeDefined();
  });

  test("an item running past the trip window clamps its continuations without crashing", () => {
    // Starts on the last day and runs 3 days — nothing beyond the window.
    const overrun = node("overrun", "2026-09-19T10:00:00Z", 4320);
    const layout = computeHorizontalLayout({
      nodes: [overrun],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: days,
    });
    expect(layout.positions.get("overrun")?.dayKey).toBe("2026-09-19");
    expect(layout.continuations).toHaveLength(0);
  });

  test("start-day duration bar still clamps at midnight", () => {
    const redEye = node("redeye", "2026-09-14T23:00:00Z", 480, "flight");
    const layout = computeHorizontalLayout({
      nodes: [redEye],
      edges: [],
      pxPerMinute: 1.2,
      tzOffsetHours: 0,
      daysMeta: days,
    });
    const p = layout.positions.get("redeye")!;
    const bottom = layout.segments[layout.segments.length - 1]!.yEnd;
    expect(p.y + p.barH).toBeLessThanOrEqual(bottom + 0.001);
  });
});
