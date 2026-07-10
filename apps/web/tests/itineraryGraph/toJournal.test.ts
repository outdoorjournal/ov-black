// Unit tests for toJournal — the Journal's narrative layout derivation
// (traveler-journal design, phase 1). This is the layout ENGINE, so the tests
// pin down every bucketing decision: day grouping + ordering, gap buckets
// (invisible / plain segment / quiet virtual node with the right period),
// night treatment from `night_bar`, visibility rules (Collection, discarded,
// attached notes), alternative grouping, and multi-day elision.

import { describe, expect, test } from "vitest";

import type { EdgeResponse, NodeResponse } from "@ov-black/api-client";

import {
  ELISION_MIN_DAYS,
  LONG_GAP_MIN,
  SHORT_GAP_MIN,
  toJournal,
  type JournalDaySection,
  type JournalEntry,
} from "@/app/_components/itinerary-graph/views/journal/toJournal";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const TZ = 9; // the Japan trip's offset

function node(
  id: string,
  startTime: string | null,
  overrides: Partial<NodeResponse> & { duration_minutes?: number } = {},
): NodeResponse {
  const { duration_minutes = 60, metadata, ...rest } = overrides;
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {
      ...(startTime ? { start_time: startTime, duration_minutes } : {}),
      ...(metadata ?? {}),
    },
    ...rest,
  } as NodeResponse;
}

function edge(
  id: string,
  from: string,
  to: string,
  type: EdgeResponse["type"] = "alternative_to",
): EdgeResponse {
  return {
    id,
    itinerary_id: "it-1",
    from_node_id: from,
    to_node_id: to,
    type,
    metadata: {},
  };
}

/** A contiguous June-2024 day scaffold starting on the 20th. */
function days(count: number): Array<{ date: string; label: string }> {
  return Array.from({ length: count }, (_, i) => ({
    date: `2024-06-${String(20 + i).padStart(2, "0")}`,
    label: `Day ${i + 1}`,
  }));
}

function journal(
  nodes: NodeResponse[],
  opts: { edges?: EdgeResponse[]; dayCount?: number } = {},
) {
  return toJournal({
    nodes,
    edges: opts.edges ?? [],
    days: days(opts.dayCount ?? 2),
    timezoneOffsetHours: TZ,
  });
}

function daySection(
  result: ReturnType<typeof toJournal>,
  index: number,
): JournalDaySection {
  const section = result.sections[index];
  if (!section || section.kind !== "day") {
    throw new Error(`sections[${index}] is not a day section`);
  }
  return section;
}

const kinds = (entries: JournalEntry[]): string[] => entries.map((e) => e.kind);

// ── Day grouping ──────────────────────────────────────────────────────────────
describe("toJournal · day grouping", () => {
  test("buckets nodes by local day and orders each day by start time", () => {
    const result = journal([
      node("b", "2024-06-20T15:00:00+09:00"),
      node("a", "2024-06-20T09:00:00+09:00"),
      node("c", "2024-06-21T10:00:00+09:00"),
    ]);
    const day1 = daySection(result, 0);
    const day2 = daySection(result, 1);
    expect(day1.label).toBe("Day 1");
    const day1Nodes = day1.entries.filter((e) => e.kind === "node");
    expect(day1Nodes.map((e) => (e.kind === "node" ? e.node.id : ""))).toEqual([
      "a",
      "b",
    ]);
    const day2Nodes = day2.entries.filter((e) => e.kind === "node");
    expect(day2Nodes.map((e) => (e.kind === "node" ? e.node.id : ""))).toEqual([
      "c",
    ]);
    expect(result.nodeCount).toBe(3);
  });

  test("a node is placed by its OWN offset (the trip spans timezones)", () => {
    // 22:00 on the 20th in −05:00 is 12:00 on the 21st in the trip's +09:00 —
    // but the node's own wall clock wins, so it belongs to Day 1.
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00"),
      node("late", "2024-06-20T22:00:00-05:00"),
    ]);
    const day1Ids = daySection(result, 0)
      .entries.filter((e) => e.kind === "node")
      .map((e) => (e.kind === "node" ? e.node.id : ""));
    expect(day1Ids).toEqual(["a", "late"]);
  });
});

// ── Gap bucketing ─────────────────────────────────────────────────────────────
describe("toJournal · gap buckets", () => {
  test(`a tiny gap (< ${SHORT_GAP_MIN}m) is invisible — the spine just continues`, () => {
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 60 }),
      node("b", "2024-06-20T10:10:00+09:00"), // 10 min after a ends
    ]);
    expect(kinds(daySection(result, 0).entries)).toEqual(["node", "node"]);
  });

  test("a short gap becomes a plain spine segment (gap entry, no card)", () => {
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 60 }),
      node("b", "2024-06-20T11:00:00+09:00"), // 60 min after a ends
    ]);
    const entries = daySection(result, 0).entries;
    expect(kinds(entries)).toEqual(["node", "gap", "node"]);
    const gap = entries[1];
    expect(gap?.kind === "gap" && gap.minutes).toBe(60);
  });

  test(`a long gap (≥ ${LONG_GAP_MIN}m) becomes a quiet virtual node with a period caption`, () => {
    // a ends 10:00; b starts 15:00 → 300 min, midpoint 12:30 → afternoon.
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 60 }),
      node("b", "2024-06-20T15:00:00+09:00"),
    ]);
    const entries = daySection(result, 0).entries;
    expect(kinds(entries)).toEqual(["node", "quiet", "node"]);
    const quiet = entries[1];
    if (quiet?.kind !== "quiet") throw new Error("expected a quiet entry");
    expect(quiet.minutes).toBe(300);
    expect(quiet.period).toBe("afternoon");
    expect(quiet.caption).toBe("A free afternoon");
  });

  test("quiet periods honor the gap's local midpoint (morning / evening)", () => {
    const morning = journal([
      node("a", "2024-06-20T07:00:00+09:00", { duration_minutes: 30 }),
      node("b", "2024-06-20T10:30:00+09:00"),
    ]);
    const mEntry = daySection(morning, 0).entries[1];
    expect(mEntry?.kind === "quiet" && mEntry.period).toBe("morning");

    const evening = journal([
      node("a", "2024-06-20T16:00:00+09:00", { duration_minutes: 60 }),
      node("b", "2024-06-20T21:00:00+09:00"),
    ]);
    const eEntry = daySection(evening, 0).entries[1];
    expect(eEntry?.kind === "quiet" && eEntry.period).toBe("evening");
  });

  test("overlapping / back-to-back entries produce no gap", () => {
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00", { duration_minutes: 180 }),
      node("b", "2024-06-20T10:00:00+09:00"), // starts inside a
    ]);
    expect(kinds(daySection(result, 0).entries)).toEqual(["node", "node"]);
  });
});

// ── Night treatment ───────────────────────────────────────────────────────────
describe("toJournal · nights", () => {
  test("a night_bar node leaves the card flow and names the day's night", () => {
    const result = journal([
      node("exp", "2024-06-20T09:00:00+09:00"),
      node("hotel-night", "2024-06-20T22:00:00+09:00", {
        type: "hotel",
        metadata: {
          start_time: "2024-06-20T22:00:00+09:00",
          duration_minutes: 540,
          night_bar: true,
        },
      }),
      node("exp2", "2024-06-21T10:00:00+09:00"),
    ]);
    const day1 = daySection(result, 0);
    // The night bar is NOT a card entry…
    expect(
      day1.entries.some((e) => e.kind === "node" && e.node.id === "hotel-night"),
    ).toBe(false);
    // …it is the day's night.
    expect(day1.night?.node?.id).toBe("hotel-night");
    expect(result.nodeCount).toBe(2);
  });

  test("a day followed by another day gets a generic night; the last day none", () => {
    const result = journal([
      node("a", "2024-06-20T09:00:00+09:00"),
      node("b", "2024-06-21T10:00:00+09:00"),
    ]);
    expect(daySection(result, 0).night).toEqual({ node: null });
    expect(daySection(result, 1).night).toBeNull();
  });
});

// ── Visibility rules ──────────────────────────────────────────────────────────
describe("toJournal · visibility", () => {
  test("unscheduled nodes (Collection) never reach the Journal", () => {
    const result = journal([
      node("scheduled", "2024-06-20T09:00:00+09:00"),
      node("no-start", null),
      node("synth", "2024-06-20T10:00:00+09:00", {
        metadata: {
          start_time: "2024-06-20T10:00:00+09:00",
          start_synthesized: true,
        },
      }),
    ]);
    expect(result.nodeCount).toBe(1);
  });

  test("discarded nodes and attached notes are excluded; free-standing notes stay", () => {
    const result = journal([
      node("host", "2024-06-20T09:00:00+09:00"),
      node("gone", "2024-06-20T11:00:00+09:00", { status: "discarded" }),
      node("margin", "2024-06-20T12:00:00+09:00", {
        type: "note",
        attached_to_node_id: "host",
      }),
      node("day-note", "2024-06-20T13:00:00+09:00", { type: "note" }),
    ]);
    const ids = daySection(result, 0)
      .entries.filter((e) => e.kind === "node")
      .map((e) => (e.kind === "node" ? e.node.id : ""));
    expect(ids).toEqual(["host", "day-note"]);
  });
});

// ── Alternative groups ────────────────────────────────────────────────────────
describe("toJournal · alternatives", () => {
  test("metadata alt_group members fold into one alt entry, ordered by start", () => {
    const result = journal([
      node("plan-b", "2024-06-20T10:30:00+09:00", {
        metadata: {
          start_time: "2024-06-20T10:30:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
      node("plan-a", "2024-06-20T10:00:00+09:00", {
        metadata: {
          start_time: "2024-06-20T10:00:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
    ]);
    const entries = daySection(result, 0).entries;
    expect(entries).toHaveLength(1);
    const alt = entries[0];
    if (alt?.kind !== "alt") throw new Error("expected an alt entry");
    expect(alt.groupKey).toBe("g1");
    expect(alt.nodes.map((n) => n.id)).toEqual(["plan-a", "plan-b"]);
    expect(result.nodeCount).toBe(2);
  });

  test("alternative_to edges group nodes without alt_group metadata", () => {
    const result = journal(
      [
        node("a", "2024-06-20T10:00:00+09:00"),
        node("b", "2024-06-20T10:30:00+09:00"),
      ],
      { edges: [edge("e1", "b", "a")] },
    );
    const entries = daySection(result, 0).entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]?.kind).toBe("alt");
  });

  test("gap bucketing measures around the whole alt group", () => {
    // Group spans 10:00–11:30; the next card at 15:00 → a quiet afternoon.
    const result = journal([
      node("a", "2024-06-20T10:00:00+09:00", {
        metadata: {
          start_time: "2024-06-20T10:00:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
      node("b", "2024-06-20T10:30:00+09:00", {
        metadata: {
          start_time: "2024-06-20T10:30:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
      node("later", "2024-06-20T15:00:00+09:00"),
    ]);
    expect(kinds(daySection(result, 0).entries)).toEqual([
      "alt",
      "quiet",
      "node",
    ]);
  });
});

// ── Empty days and elision ────────────────────────────────────────────────────
describe("toJournal · empty days and elision", () => {
  test("a single empty day reads as an open day, not an elision", () => {
    const result = journal(
      [
        node("a", "2024-06-20T09:00:00+09:00"),
        node("c", "2024-06-22T09:00:00+09:00"),
      ],
      { dayCount: 3 },
    );
    expect(result.sections).toHaveLength(3);
    const openDay = daySection(result, 1);
    const only = openDay.entries[0];
    expect(openDay.entries).toHaveLength(1);
    if (only?.kind !== "quiet") throw new Error("expected a quiet entry");
    expect(only.period).toBe("day");
    expect(only.caption).toBe("An open day");
  });

  test(`${ELISION_MIN_DAYS}+ consecutive empty days collapse into an elision marker`, () => {
    // Content on Day 1 and Day 10; Days 2–9 are empty.
    const result = journal(
      [
        node("a", "2024-06-20T09:00:00+09:00"),
        node("z", "2024-06-29T09:00:00+09:00"),
      ],
      { dayCount: 10 },
    );
    expect(result.sections).toHaveLength(3);
    const elision = result.sections[1];
    if (elision?.kind !== "elision") throw new Error("expected an elision");
    expect(elision.startLabel).toBe("Day 2");
    expect(elision.endLabel).toBe("Day 9");
    expect(elision.dayCount).toBe(8);
    expect(elision.days.map((d) => d.label)).toEqual([
      "Day 2",
      "Day 3",
      "Day 4",
      "Day 5",
      "Day 6",
      "Day 7",
      "Day 8",
      "Day 9",
    ]);
  });

  test("a day carrying only a night_bar is not elided (the night anchors it)", () => {
    const result = journal(
      [
        node("a", "2024-06-20T09:00:00+09:00"),
        node("night2", "2024-06-21T22:00:00+09:00", {
          type: "hotel",
          metadata: {
            start_time: "2024-06-21T22:00:00+09:00",
            duration_minutes: 540,
            night_bar: true,
          },
        }),
        node("night3", "2024-06-22T22:00:00+09:00", {
          type: "hotel",
          metadata: {
            start_time: "2024-06-22T22:00:00+09:00",
            duration_minutes: 540,
            night_bar: true,
          },
        }),
        node("z", "2024-06-23T09:00:00+09:00"),
      ],
      { dayCount: 4 },
    );
    expect(result.sections.every((s) => s.kind === "day")).toBe(true);
    expect(daySection(result, 1).night?.node?.id).toBe("night2");
  });

  test("an itinerary with nothing scheduled reports nodeCount 0", () => {
    const result = journal([], { dayCount: 5 });
    expect(result.nodeCount).toBe(0);
  });
});
