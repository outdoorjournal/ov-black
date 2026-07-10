// Embedded subgraphs (PRD "subgraphs for self-contained experiences"): a
// multi-day inventory card materializes day children under parent_subgraph_id.
// These tests pin the read-side contract: children group + order by day index,
// they never leak into the Collection or get synthesized layout time, and the
// Journal lays them onto their calendar days as DERIVED journey beats — day k
// of the journey on parentDay + (k-1), wearing membership info — so the span
// reads across the days it covers.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return { ...actual, createApiClient: vi.fn(() => ({})) };
});

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import {
  isSubgraphChild,
  stripHtml,
  subgraphChildrenByParent,
} from "@/app/_components/itinerary-graph/shared/subgraph";
import { collectionItemsOf } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { toItineraryTimeline } from "@/app/_components/itinerary-graph/adapter/toItineraryTimeline";
import {
  toJournal,
  type JournalDaySection,
} from "@/app/_components/itinerary-graph/views/journal/toJournal";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";

afterEach(cleanup);

function makeNode(id: string, overrides: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...overrides,
  } as NodeResponse;
}

function dayChild(
  id: string,
  parent: string,
  index: number,
  overrides: Partial<NodeResponse> = {},
): NodeResponse {
  return makeNode(id, {
    parent_subgraph_id: parent,
    title: `Day ${index} — Leg ${index}`,
    metadata: {
      snapshot: { title: `Leg ${index}`, location: "Amhara, Ethiopia" },
      subgraph_day: { index, hours: 9, lat: 13.18, lng: 38.13 },
    },
    ...overrides,
  });
}

/** A scheduled 4-day parent starting 2024-06-21 08:00 (+03), with 4 children. */
function simienFixture(): { parent: NodeResponse; children: NodeResponse[] } {
  const parent = makeNode("p1", {
    title: "4 Days Simien Mountain Wildlife Safari",
    metadata: {
      start_time: "2024-06-21T08:00:00+03:00",
      duration_minutes: 4 * 24 * 60,
    },
  });
  const children = [1, 2, 3, 4].map((i) => dayChild(`d${i}`, "p1", i));
  return { parent, children };
}

const DAYS = Array.from({ length: 6 }, (_, i) => ({
  date: `2024-06-${String(20 + i).padStart(2, "0")}`,
  label: `Day ${i + 1}`,
}));

function daySection(
  journal: ReturnType<typeof toJournal>,
  date: string,
): JournalDaySection | null {
  const section = journal.sections.find(
    (s) => s.kind === "day" && s.date === date,
  );
  return section?.kind === "day" ? section : null;
}

describe("subgraphChildrenByParent", () => {
  test("groups by parent and orders by day index", () => {
    const parent = makeNode("p1");
    const kids = [
      dayChild("d3", "p1", 3),
      dayChild("d1", "p1", 1),
      dayChild("d2", "p1", 2),
    ];
    const map = subgraphChildrenByParent([parent, ...kids]);
    expect(map.get("p1")?.map((n) => n.id)).toEqual(["d1", "d2", "d3"]);
    expect(isSubgraphChild(parent)).toBe(false);
    expect(isSubgraphChild(kids[0] as NodeResponse)).toBe(true);
  });

  test("drops discarded children", () => {
    const map = subgraphChildrenByParent([
      dayChild("d1", "p1", 1),
      dayChild("d2", "p1", 2, { status: "discarded" }),
    ]);
    expect(map.get("p1")?.map((n) => n.id)).toEqual(["d1"]);
  });
});

describe("stripHtml", () => {
  test("flattens vendor HTML to plain text", () => {
    expect(stripHtml("<p>Fly to <em>Gondar</em>.</p><h3>Then&nbsp;drive</h3>")).toBe(
      "Fly to Gondar . Then drive",
    );
  });
});

describe("collection exclusion", () => {
  test("subgraph children never appear as wish-list items", () => {
    const items = collectionItemsOf(
      [makeNode("p1"), dayChild("d1", "p1", 1)],
      [],
    );
    expect(items.map((n) => n.id)).toEqual(["p1"]);
  });
});

describe("adapter", () => {
  const ITINERARY: ItineraryResponse = {
    id: "it-1",
    title: "Ethiopia",
    client_id: "c-1",
    created_by: "u-1",
    display_status: "in_studio",
  };

  test("children get no synthesized layout time", () => {
    const timeline = toItineraryTimeline(
      ITINERARY,
      [makeNode("p1"), dayChild("d1", "p1", 1)],
      [],
      { synthAnchorDate: "2024-06-20" },
    );
    const parent = timeline.nodes.find((n) => n.id === "p1");
    const child = timeline.nodes.find((n) => n.id === "d1");
    // The undated parent is synthesized onto the board; the child is not.
    expect((parent?.metadata as { start_time?: string }).start_time).toBeTruthy();
    expect((child?.metadata as { start_time?: string }).start_time).toBeUndefined();
    // The child still rides through for the journey-beat derivation.
    expect(child).toBeDefined();
  });
});

describe("journey beats", () => {
  test("a scheduled parent lays its children onto consecutive days", () => {
    const { parent, children } = simienFixture();
    const journal = toJournal({
      nodes: [parent, ...children],
      edges: [],
      days: DAYS,
      timezoneOffsetHours: 3,
    });
    // Parent + 4 derived beats all count as story nodes.
    expect(journal.nodeCount).toBe(5);

    // Day 2 of the scaffold (2024-06-21, the parent's day): parent card first,
    // then day-1's beat riding the same instant.
    const startDay = daySection(journal, "2024-06-21");
    const startNodes = (startDay?.entries ?? []).filter((e) => e.kind === "node");
    expect(startNodes.map((e) => (e.kind === "node" ? e.node.id : ""))).toEqual([
      "p1",
      "d1",
    ]);
    const beat1 = startNodes[1];
    expect(beat1?.kind === "node" && beat1.journey).toMatchObject({
      parentId: "p1",
      index: 1,
      total: 4,
    });

    // Days 2..4 of the journey land on the following calendar days at 09:00.
    for (const [offset, childId] of [
      [1, "d2"],
      [2, "d3"],
      [3, "d4"],
    ] as const) {
      const date = `2024-06-${21 + offset}`;
      const section = daySection(journal, date);
      const nodeEntries = (section?.entries ?? []).filter(
        (e) => e.kind === "node",
      );
      expect(
        nodeEntries.map((e) => (e.kind === "node" ? e.node.id : "")),
      ).toEqual([childId]);
      const entry = nodeEntries[0];
      if (entry?.kind !== "node") throw new Error("expected node entry");
      expect(entry.journey?.index).toBe(offset + 1);
      expect(
        (entry.node.metadata as { start_time?: string }).start_time,
      ).toBe(`${date}T09:00:00+03:00`);
      // Vendor hours drive the beat's width (9h).
      expect(
        (entry.node.metadata as { duration_minutes?: number }).duration_minutes,
      ).toBe(540);
    }

    // The covered days are no longer empty — no elision through the journey.
    expect(journal.sections.every((s) => s.kind === "day")).toBe(true);
  });

  test("an unscheduled parent derives no beats", () => {
    const { parent, children } = simienFixture();
    const unscheduled = { ...parent, metadata: {} } as NodeResponse;
    const journal = toJournal({
      nodes: [unscheduled, ...children],
      edges: [],
      days: DAYS,
      timezoneOffsetHours: 3,
    });
    expect(journal.nodeCount).toBe(0);
  });

  test("rendered journal: thread, chips, span caption, and rail parent context", () => {
    const { parent, children } = simienFixture();
    const itinerary: ItineraryResponse = {
      id: "it-1",
      title: "Ethiopia",
      client_id: "c-1",
      created_by: "u-1",
      display_status: "with_traveler",
    };
    const timeline: ItineraryTimeline = {
      id: "it-1",
      label: "Ethiopia",
      subtitle: "",
      mood: "verdant",
      timezoneOffsetHours: 3,
      windowStart: "2024-06-20T00:00:00+03:00",
      windowEnd: "2024-06-25T23:59:00+03:00",
      days: DAYS,
      itinerary,
      nodes: [parent, ...children],
      edges: [],
    };
    const init: ItineraryGraphInit = {
      timeline,
      itineraryId: "it-1",
      status: "with_traveler",
      role: "client",
      apiBaseUrl: "http://api.test",
      accessToken: "tok",
    };
    render(
      <itineraryGraphStore.Provider initial={init}>
        <TimelineDataProvider value={{ timeline, baselineTitle: null }}>
          <JournalView railIdle={<div data-testid="stub-idle" />} />
        </TimelineDataProvider>
      </itineraryGraphStore.Provider>,
    );

    // The journey thread runs through every covered day (parent day + 3 more).
    expect(screen.getAllByTestId("journal-journey-thread")).toHaveLength(4);
    // The parent card wears the span caption; each beat wears its chip.
    expect(screen.getByTestId("journal-journey-span").textContent).toContain(
      "a 4-day journey",
    );
    const chips = screen.getAllByTestId("journal-journey-chip");
    expect(chips).toHaveLength(4);
    expect(chips[1]?.textContent).toContain("day 2 of 4");

    // Focusing a beat puts the PARENT card above its detail in the rail.
    const beatRow = screen
      .getAllByTestId("journal-node")
      .find((el) => el.getAttribute("data-node-id") === "d3");
    expect(beatRow).toBeDefined();
    fireEvent.click(beatRow!.querySelector("button")!);
    const context = screen.getByTestId("journey-parent-context");
    expect(context.textContent).toContain("part of · day 3 of 4");
    expect(context.textContent).toContain(
      "4 Days Simien Mountain Wildlife Safari",
    );
  });

  test("a raw child never lands on the spine at its own claimed time", () => {
    // Belt-and-braces: even if a child somehow carries a start_time, it is
    // excluded as a raw node — only the derived beat placement counts.
    const { parent, children } = simienFixture();
    const rogue = {
      ...children[0],
      metadata: {
        ...(children[0] as NodeResponse).metadata,
        start_time: "2024-06-25T10:00:00+03:00",
      },
    } as NodeResponse;
    const journal = toJournal({
      nodes: [parent, rogue],
      edges: [],
      days: DAYS,
      timezoneOffsetHours: 3,
    });
    // One parent + one derived beat (on the parent's day, not June 25).
    expect(journal.nodeCount).toBe(2);
    const june25 = daySection(journal, "2024-06-25");
    expect(
      (june25?.entries ?? []).filter((e) => e.kind === "node"),
    ).toHaveLength(0);
  });
});
