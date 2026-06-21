// Unit tests for the API-graph → ItineraryTimeline adapter.
//
// Focus on the three things the adapter actually decides: per-node start_time
// resolution (metadata.start_time > node.starts_at > synthesis), tz recovery
// from metadata datetimes (the column normalizes to UTC so the offset must be
// inferred), and contiguous day-span construction.

import { describe, expect, test } from "vitest";

import type {
  EdgeResponse,
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import {
  inferTzOffsetHours,
  parseOffsetHours,
  toItineraryTimeline,
} from "@/app/_components/itinerary-graph/adapter/toItineraryTimeline";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Tokyo trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

type NodeOverrides = Partial<NodeResponse> & {
  starts_at?: string | null;
  duration_minutes?: number | null;
};

function makeNode(id: string, overrides: NodeOverrides = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...overrides,
  } as NodeResponse;
}

function meta(node: NodeResponse): {
  start_time?: string;
  duration_minutes?: number;
} {
  return node.metadata as { start_time?: string; duration_minutes?: number };
}

describe("parseOffsetHours", () => {
  test("UTC forms → 0", () => {
    expect(parseOffsetHours("2024-06-20T07:10:00Z")).toBe(0);
    expect(parseOffsetHours("2024-06-20T07:10:00+00:00")).toBe(0);
  });
  test("offset forms", () => {
    expect(parseOffsetHours("2024-06-20T16:10:00+09:00")).toBe(9);
    expect(parseOffsetHours("2024-06-20T16:10:00-05:30")).toBe(-5.5);
  });
  test("no offset → null", () => {
    expect(parseOffsetHours("2024-06-20T16:10:00")).toBeNull();
  });
});

describe("inferTzOffsetHours", () => {
  test("recovers a non-UTC offset from a metadata datetime field", () => {
    const nodes = [
      makeNode("a", {
        starts_at: "2024-06-20T07:10:00+00:00", // UTC-normalized
        metadata: { depart_at: "2024-06-20T16:10:00+09:00" }, // keeps offset
      }),
    ];
    expect(inferTzOffsetHours(nodes)).toBe(9);
  });

  test("all-UTC → 0", () => {
    const nodes = [
      makeNode("a", { metadata: { check_in: "2024-06-20T07:10:00+00:00" } }),
    ];
    expect(inferTzOffsetHours(nodes)).toBe(0);
  });
});

describe("toItineraryTimeline — start_time resolution", () => {
  test("prefers metadata.start_time over starts_at", () => {
    const node = makeNode("a", {
      starts_at: "2024-06-20T00:00:00+00:00",
      metadata: { start_time: "2024-06-20T09:30:00+00:00" },
    });
    const tl = toItineraryTimeline(ITINERARY, [node], []);
    expect(meta(tl.nodes[0]!).start_time).toBe("2024-06-20T09:30:00+00:00");
  });

  test("falls back to node.starts_at when metadata has none", () => {
    const node = makeNode("a", { starts_at: "2024-06-20T09:30:00+00:00" });
    const tl = toItineraryTimeline(ITINERARY, [node], []);
    expect(meta(tl.nodes[0]!).start_time).toBe("2024-06-20T09:30:00+00:00");
  });

  test("synthesizes a start for an undated node onto the anchor day", () => {
    const node = makeNode("a"); // no timing anywhere
    const tl = toItineraryTimeline(ITINERARY, [node], [], {
      synthAnchorDate: "2024-06-20",
    });
    const start = meta(tl.nodes[0]!).start_time;
    expect(start).toBeDefined();
    // synth places the first undated node at 09:00 on the anchor day.
    expect(start).toContain("2024-06-20T09:00");
  });
});

describe("toItineraryTimeline — duration resolution", () => {
  test("metadata.duration_minutes wins", () => {
    const node = makeNode("a", {
      starts_at: "2024-06-20T09:00:00+00:00",
      duration_minutes: 30,
      metadata: { duration_minutes: 90 },
    });
    const tl = toItineraryTimeline(ITINERARY, [node], []);
    expect(meta(tl.nodes[0]!).duration_minutes).toBe(90);
  });

  test("falls back to node.duration_minutes, then type default", () => {
    const a = makeNode("a", {
      type: "experience",
      starts_at: "2024-06-20T09:00:00+00:00",
      duration_minutes: 45,
    });
    const b = makeNode("b", {
      type: "hotel",
      starts_at: "2024-06-20T21:00:00+00:00",
    });
    const tl = toItineraryTimeline(ITINERARY, [a, b], []);
    const byId = new Map(tl.nodes.map((n) => [n.id, n]));
    expect(meta(byId.get("a")!).duration_minutes).toBe(45);
    expect(meta(byId.get("b")!).duration_minutes).toBe(540); // hotel default
  });
});

describe("toItineraryTimeline — days + tz", () => {
  test("builds a contiguous day span and recovers the trip tz", () => {
    const day1 = makeNode("d1", {
      starts_at: "2024-06-20T07:10:00+00:00", // 16:10 JST
      metadata: { depart_at: "2024-06-20T16:10:00+09:00" },
    });
    const day3 = makeNode("d3", {
      starts_at: "2024-06-22T01:00:00+00:00", // 10:00 JST on the 22nd
      metadata: {},
    });
    const tl = toItineraryTimeline(ITINERARY, [day1, day3], []);
    expect(tl.timezoneOffsetHours).toBe(9);
    // 20th, 21st, 22nd inclusive — even though the 21st has no nodes.
    expect(tl.days.map((d) => d.date)).toEqual([
      "2024-06-20",
      "2024-06-21",
      "2024-06-22",
    ]);
    expect(tl.label).toBe("Tokyo trip");
    expect(tl.id).toBe("it-1");
  });

  test("every returned node carries start_time + duration_minutes", () => {
    const nodes = [
      makeNode("a", { starts_at: "2024-06-20T09:00:00+00:00" }),
      makeNode("b"), // undated → synthesized
    ];
    const tl = toItineraryTimeline(ITINERARY, nodes, [], {
      synthAnchorDate: "2024-06-20",
    });
    for (const n of tl.nodes) {
      expect(meta(n).start_time).toBeDefined();
      expect(typeof meta(n).duration_minutes).toBe("number");
    }
  });
});
