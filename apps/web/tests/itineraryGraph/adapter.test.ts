// Unit tests for the API-graph → ItineraryTimeline adapter.
//
// Focus on the three things the adapter actually decides: per-node start_time
// resolution (metadata.start_time > server schedule view > node.starts_at >
// synthesis), consuming the server's resolved schedule views (Phase 4,
// doc/itin-time.md — tz + day come from the kernel, not inference), and
// contiguous day-span construction.

import { describe, expect, test } from "vitest";

import type {
  ItineraryResponse,
  NodeResponse,
  ResolvedScheduleResponse,
} from "@ov-black/api-client";

import {
  parseOffsetHours,
  toItineraryTimeline,
} from "@/app/_components/itinerary-graph/adapter/toItineraryTimeline";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Tokyo trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
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

// A server-resolved schedule view (Phase 4) — relative, one endpoint.
function relativeView(
  dayIndex: number,
  date: string,
  wallTime: string,
  tz: string,
  instant: string,
  synthesized = false,
): ResolvedScheduleResponse {
  return {
    kind: "relative",
    start: { day_index: dayIndex, date, wall_time: wallTime, tz, instant },
    end: null,
    day_span: 1,
    synthesized,
  };
}

describe("toItineraryTimeline — server-resolved schedule views (Phase 4)", () => {
  test("trip tz comes from the schedule view's resolved instant, not inference", () => {
    const node = makeNode("a", {
      starts_at: "2024-06-20T16:10:00+09:00",
      metadata: { start_time: "2024-06-20T16:10:00+09:00" },
      schedule: relativeView(
        1,
        "2024-06-20",
        "16:10",
        "Asia/Tokyo",
        "2024-06-20T16:10:00+09:00",
      ),
    } as NodeOverrides);
    const tl = toItineraryTimeline(ITINERARY, [node], []);
    expect(tl.timezoneOffsetHours).toBe(9);
  });

  test("day_key is stamped from the server view's local date", () => {
    // A late-night LA start: instant 06:00Z on the 21st, LOCAL date the 20th.
    // The server view's date is authoritative — no client offset math.
    const node = makeNode("la", {
      starts_at: "2024-06-20T23:00:00-07:00",
      metadata: { start_time: "2024-06-20T23:00:00-07:00" },
      schedule: relativeView(
        1,
        "2024-06-20",
        "23:00",
        "America/Los_Angeles",
        "2024-06-20T23:00:00-07:00",
      ),
    } as NodeOverrides);
    const tl = toItineraryTimeline(ITINERARY, [node], []);
    expect(
      (tl.nodes[0]!.metadata as { day_key?: string }).day_key,
    ).toBe("2024-06-20");
  });

  test("a server-synthesized slot renders as a start_synthesized placement", () => {
    const wish = makeNode("wish", {
      schedule: relativeView(
        1,
        "2026-08-10",
        "09:00",
        "Europe/Athens",
        "2026-08-10T09:00:00+03:00",
        true,
      ),
    } as NodeOverrides);
    const tl = toItineraryTimeline(ITINERARY, [wish], []);
    const m = tl.nodes[0]!.metadata as {
      start_time?: string;
      start_synthesized?: boolean;
      day_key?: string;
    };
    expect(m.start_time).toBe("2026-08-10T09:00:00+03:00");
    expect(m.start_synthesized).toBe(true);
    expect(m.day_key).toBe("2026-08-10");
  });

  test("a synthesized slot with no instant (undated trip) projects onto Day 1", () => {
    const wish = makeNode("wish", {
      schedule: {
        kind: "relative",
        start: {
          day_index: 1,
          date: null,
          wall_time: "09:00",
          tz: "UTC",
          instant: null,
        },
        end: null,
        day_span: 1,
        synthesized: true,
      },
    } as NodeOverrides);
    const tl = toItineraryTimeline(ITINERARY, [wish], [], {
      synthAnchorDate: "2026-08-10",
    });
    const m = tl.nodes[0]!.metadata as { start_time?: string };
    expect(m.start_time).toContain("2026-08-10T09:00");
  });

  test("dayOneKey follows the server anchor_date over the visual first day", () => {
    const anchored: ItineraryResponse = {
      ...ITINERARY,
      anchor_date: "2026-08-10",
    } as ItineraryResponse;
    // A card scheduled BEFORE Day 1 (outbound leaving home the day before)
    // extends the visual span, but Day 1's identity stays the anchor.
    const early = makeNode("early", {
      starts_at: "2026-08-09T17:00:00+00:00",
      metadata: { start_time: "2026-08-09T17:00:00+00:00" },
    });
    const tl = toItineraryTimeline(anchored, [early], []);
    expect(tl.dayOneKey).toBe("2026-08-10");
    expect(tl.days[0]!.date).toBe("2026-08-09");
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

describe("toItineraryTimeline — flight timing is intrinsic", () => {
  test("a flight pins to depart_at + its leg, overriding a generic placement", () => {
    const flight = makeNode("f", {
      type: "flight",
      // A stale generic placement (noon + 2h) picked up when the card was placed
      // from the Collection — the flight's own times must win over it.
      starts_at: "2026-11-10T12:00:00-03:00",
      duration_minutes: 120,
      metadata: {
        start_time: "2026-11-10T12:00:00-03:00",
        duration_minutes: 120,
        depart_at: "2026-11-10T16:10:00-05:00",
        arrive_at: "2026-11-11T07:50:00-03:00",
      },
    });
    const tl = toItineraryTimeline(ITINERARY, [flight], []);
    const m = meta(tl.nodes[0]!);
    // Start is the real departure, not the noon slot.
    expect(m.start_time).toBe("2026-11-10T16:10:00-05:00");
    // Duration is the real leg: depart 21:10Z (16:10 -05:00) → arrive 10:50Z next
    // day (07:50 -03:00) = 13h40m, not the 2h default/stale value.
    expect(m.duration_minutes).toBe(820);
  });

  test("a flight missing arrive_at keeps its depart_at start, default duration", () => {
    const flight = makeNode("f", {
      type: "flight",
      metadata: { depart_at: "2026-11-10T16:10:00-05:00" },
    });
    const tl = toItineraryTimeline(ITINERARY, [flight], []);
    const m = meta(tl.nodes[0]!);
    expect(m.start_time).toBe("2026-11-10T16:10:00-05:00");
    expect(m.duration_minutes).toBe(120); // flight type default
  });
});

describe("toItineraryTimeline — days + tz", () => {
  test("builds a contiguous day span; tz comes from the server views", () => {
    const day1 = makeNode("d1", {
      starts_at: "2024-06-20T16:10:00+09:00",
      schedule: relativeView(
        1,
        "2024-06-20",
        "16:10",
        "Asia/Tokyo",
        "2024-06-20T16:10:00+09:00",
      ),
    } as NodeOverrides);
    const day3 = makeNode("d3", {
      starts_at: "2024-06-22T10:00:00+09:00",
      schedule: relativeView(
        3,
        "2024-06-22",
        "10:00",
        "Asia/Tokyo",
        "2024-06-22T10:00:00+09:00",
      ),
    } as NodeOverrides);
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

  test("buckets each node by its OWN offset (multi-tz trip)", () => {
    // A trip spans timezones: a late-night LA node and a next-morning Tokyo
    // node. By instant, Tokyo (23:00Z on the 20th) precedes LA (06:00Z on the
    // 21st) — but by LOCAL date LA is the 20th and Tokyo the 21st.
    const la = makeNode("la", {
      starts_at: "2024-06-20T23:00:00-07:00",
    });
    const tokyo = makeNode("tokyo", {
      starts_at: "2024-06-21T08:00:00+09:00",
    });
    const tl = toItineraryTimeline(ITINERARY, [la, tokyo], []);
    const byId = new Map(tl.nodes.map((n) => [n.id, n]));
    // Each node keeps its own offset on start_time.
    expect(meta(byId.get("la")!).start_time).toBe("2024-06-20T23:00:00-07:00");
    expect(meta(byId.get("tokyo")!).start_time).toBe(
      "2024-06-21T08:00:00+09:00",
    );
    // Days span the two LOCAL dates, not the instant order.
    expect(tl.days.map((d) => d.date)).toEqual(["2024-06-20", "2024-06-21"]);
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

describe("toItineraryTimeline — exact trip window (0033)", () => {
  const EXACT: ItineraryResponse = {
    ...ITINERARY,
    timing_kind: "exact",
    date_start: "2026-08-10",
    date_end: "2026-08-18",
  };

  test("empty exact itinerary spans the full date window", () => {
    const tl = toItineraryTimeline(EXACT, [], []);
    // Aug 10 → 18 inclusive = 9 days, even with nothing scheduled.
    expect(tl.days.map((d) => d.date)).toEqual([
      "2026-08-10",
      "2026-08-11",
      "2026-08-12",
      "2026-08-13",
      "2026-08-14",
      "2026-08-15",
      "2026-08-16",
      "2026-08-17",
      "2026-08-18",
    ]);
    expect(tl.windowStart.startsWith("2026-08-10")).toBe(true);
    expect(tl.windowEnd.startsWith("2026-08-18")).toBe(true);
  });

  test("an undated node lands on the trip window, not today", () => {
    const tl = toItineraryTimeline(EXACT, [makeNode("a")], []);
    // Synth anchor is date_start, so the first undated card sits on Aug 10.
    expect(meta(tl.nodes[0]!).start_time?.startsWith("2026-08-10")).toBe(true);
  });

  test("a node outside the window extends the span", () => {
    const tl = toItineraryTimeline(
      EXACT,
      [makeNode("late", { starts_at: "2026-08-20T09:00:00+00:00" })],
      [],
    );
    // Window ends Aug 18 but a node on Aug 20 stretches the span to cover it.
    expect(tl.days[0]!.date).toBe("2026-08-10");
    expect(tl.days[tl.days.length - 1]!.date).toBe("2026-08-20");
  });

  test("an empty loose window scaffolds a week, never the whole window", () => {
    // A loose window with dates set but nothing scheduled must NOT fabricate a
    // wall of empty days (the 92-day window) — an empty non-exact trip gets
    // the default 7-day canvas (QA-13) anchored on the window start.
    const loose: ItineraryResponse = {
      ...ITINERARY,
      timing_kind: "window",
      date_start: "2026-06-01",
      date_end: "2026-08-31",
    };
    const tl = toItineraryTimeline(loose, [], [], {
      synthAnchorDate: "2026-06-15",
    });
    expect(tl.days).toHaveLength(7);
    expect(tl.days[0]!.date).toBe("2026-06-15");
    expect(tl.days[0]!.label).toBe("Day 1");
    expect(tl.days[6]!.label).toBe("Day 7");
  });

  test("an empty trip with a captured duration scaffolds nights + 1 days", () => {
    const loose: ItineraryResponse = {
      ...ITINERARY,
      timing_kind: "window",
      date_start: "2026-06-01",
      date_end: "2026-08-31",
      duration_nights: 9,
    };
    const tl = toItineraryTimeline(loose, [], [], {
      synthAnchorDate: "2026-06-15",
    });
    expect(tl.days).toHaveLength(10);
  });

  test("the first real node collapses the scaffold back to node-driven", () => {
    const loose: ItineraryResponse = {
      ...ITINERARY,
      timing_kind: "window",
      date_start: "2026-06-01",
      date_end: "2026-08-31",
    };
    const tl = toItineraryTimeline(
      loose,
      [makeNode("a", { starts_at: "2026-06-15T09:00:00+00:00" })],
      [],
    );
    expect(tl.days).toHaveLength(1);
    expect(tl.days[0]!.date).toBe("2026-06-15");
  });
});

describe("toItineraryTimeline — Day-1 anchor (0041, Wave E / ADV-16)", () => {
  const WINDOWED: ItineraryResponse = {
    ...ITINERARY,
    timing_kind: "window",
    date_start: "2026-06-01",
    date_end: "2026-08-31",
    days_anchor: "2026-06-01",
  };

  test("the stamped anchor wins over the earliest card — Day-N numbering is stable", () => {
    // Only a "Day 3" card remains (the Day-1 card was deleted). Numbering must
    // still count from the anchor: the card's day is labeled Day 3, not Day 1.
    const tl = toItineraryTimeline(
      WINDOWED,
      [makeNode("dinner", { starts_at: "2026-06-03T19:00:00+02:00" })],
      [],
    );
    expect(tl.days[0]!.date).toBe("2026-06-01");
    expect(tl.days.map((d) => d.label)).toEqual(["Day 1", "Day 2", "Day 3"]);
  });

  test("undated cards land on the anchor day, not the earliest dated card", () => {
    const tl = toItineraryTimeline(
      WINDOWED,
      [
        makeNode("dated", { starts_at: "2026-06-03T19:00:00+02:00" }),
        makeNode("undated"),
      ],
      [],
    );
    expect(meta(tl.nodes[1]!).start_time?.startsWith("2026-06-01")).toBe(true);
  });

  test("an empty windowed trip with no anchor lays out from the window start", () => {
    // …the same date the server will stamp as days_anchor when the first card
    // lands, so the provisional layout and the stamped anchor agree.
    const { days_anchor: _anchor, ...rest } = WINDOWED;
    const noAnchor = rest as ItineraryResponse;
    const tl = toItineraryTimeline(noAnchor, [makeNode("undated")], []);
    expect(meta(tl.nodes[0]!).start_time?.startsWith("2026-06-01")).toBe(true);
  });

  test("a legacy windowed trip (cards, no anchor) stays card-driven", () => {
    const { days_anchor: _anchor, ...rest } = WINDOWED;
    const noAnchor = rest as ItineraryResponse;
    const tl = toItineraryTimeline(
      noAnchor,
      [makeNode("dated", { starts_at: "2026-07-10T10:00:00+02:00" })],
      [],
    );
    // No anchor stamped → the earliest card anchors, exactly as before 0041.
    expect(tl.days[0]!.date).toBe("2026-07-10");
    expect(tl.days[0]!.label).toBe("Day 1");
  });

  test("a pinned trip ignores a stale pre-pin anchor — date_start is Day 1", () => {
    // Regression: a note added before dates were set stamped days_anchor at
    // "today" (Jul 11); the trip was later pinned to start Jul 18. The stale
    // anchor must NOT inject phantom leading days that push the first real card
    // to "Day 8" — on an exact trip date_start is Day 1.
    const pinnedStaleAnchor: ItineraryResponse = {
      ...ITINERARY,
      timing_kind: "exact",
      date_start: "2026-07-18",
      date_end: "2026-07-27",
      days_anchor: "2026-07-11",
    };
    const tl = toItineraryTimeline(
      pinnedStaleAnchor,
      [makeNode("flight", { starts_at: "2026-07-18T13:09:00-04:00" })],
      [],
    );
    expect(tl.days[0]!.date).toBe("2026-07-18");
    expect(tl.days[0]!.label).toBe("Day 1");
  });
});
