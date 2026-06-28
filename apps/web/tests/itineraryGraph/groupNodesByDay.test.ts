// Tests for the shared day-bucketing helpers that power the mobile day strip
// + timeline and the proposal "jump to day" routing. Pure functions — no DOM.

import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import {
  dayIndexForNode,
  dayKeyForNode,
  groupNodesByDay,
} from "@/app/_components/itinerary-graph/shared/groupNodesByDay";

function node(
  id: string,
  start: string | null,
  extra: Partial<NodeResponse> = {},
): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: start ? { start_time: start } : {},
    ...extra,
  };
}

const DAYS = [
  { date: "2024-06-20", label: "Day 1" },
  { date: "2024-06-21", label: "Day 2" },
  { date: "2024-06-22", label: "Day 3", weather_emoji: "☀️" },
];
const TZ = 9; // Tokyo

describe("dayKeyForNode", () => {
  test("uses the node's explicit offset", () => {
    expect(dayKeyForNode(node("a", "2024-06-21T08:00:00+09:00"), TZ)).toBe(
      "2024-06-21",
    );
  });

  test("places a node by its local day, not its UTC instant", () => {
    // 01:00 +09:00 is still 2024-06-21T16:00Z, but the traveler's local day is
    // the 22nd — the helper must honor the offset, not the UTC date.
    expect(dayKeyForNode(node("b", "2024-06-22T01:00:00+09:00"), TZ)).toBe(
      "2024-06-22",
    );
  });

  test("returns null when the node has no start_time", () => {
    expect(dayKeyForNode(node("c", null), TZ)).toBeNull();
  });
});

describe("groupNodesByDay", () => {
  test("buckets nodes into their day and sorts each day by start time", () => {
    const nodes = [
      node("d1-late", "2024-06-20T15:00:00+09:00"),
      node("d1-early", "2024-06-20T09:00:00+09:00"),
      node("d3", "2024-06-22T12:00:00+09:00"),
    ];
    const groups = groupNodesByDay(nodes, DAYS, TZ);

    expect(groups).toHaveLength(3);
    expect(groups[0]!.items.map((n) => n.id)).toEqual(["d1-early", "d1-late"]);
    expect(groups[1]!.items).toHaveLength(0);
    expect(groups[2]!.items.map((n) => n.id)).toEqual(["d3"]);
  });

  test("drops nodes with no start or outside the window", () => {
    const groups = groupNodesByDay(
      [
        node("no-start", null),
        node("off-window", "2024-06-25T10:00:00+09:00"),
        node("in-window", "2024-06-21T10:00:00+09:00"),
      ],
      DAYS,
      TZ,
    );
    const placed = groups.flatMap((g) => g.items.map((n) => n.id));
    expect(placed).toEqual(["in-window"]);
  });

  test("carries weather_emoji only for days that have one", () => {
    const groups = groupNodesByDay([], DAYS, TZ);
    expect(groups[0]).not.toHaveProperty("weather_emoji");
    expect(groups[2]!.weather_emoji).toBe("☀️");
  });

  test("preserves day order and labels even when empty", () => {
    const groups = groupNodesByDay([], DAYS, TZ);
    expect(groups.map((g) => g.label)).toEqual(["Day 1", "Day 2", "Day 3"]);
  });
});

describe("dayIndexForNode", () => {
  test("returns the index of the node's day column", () => {
    expect(dayIndexForNode(node("p", "2024-06-22T09:00:00+09:00"), DAYS, TZ)).toBe(
      2,
    );
  });

  test("returns -1 for a start-less node", () => {
    expect(dayIndexForNode(node("p", null), DAYS, TZ)).toBe(-1);
  });

  test("returns -1 when the node falls outside the window", () => {
    expect(
      dayIndexForNode(node("p", "2024-07-01T09:00:00+09:00"), DAYS, TZ),
    ).toBe(-1);
  });
});
