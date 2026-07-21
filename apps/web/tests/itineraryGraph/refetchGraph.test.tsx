// refetchGraph — the `itinerary_updated` refetch-and-merge. When the agent
// moves the trip's dates (flexible → real), the kernel re-resolves every
// relative placement server-side, but the graph store deliberately survives
// `router.refresh()`: its nodes would keep start_times resolved under the OLD
// anchor, land on none of the fresh scaffold's days, and the Journal would
// render its empty invite over a full trip (the "Wide open possibilities"
// wipe). refetchGraph re-reads the graph and merges the fresh resolved views
// by node id — keeping store-only nodes and NOT inserting server-only ones
// (those arrive via their own `node_created` frames, preserving the reveal).

import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getItinerary: vi.fn(),
}));

import { getItinerary } from "@ov-black/api-client";

import type {
  ItineraryResponse,
  ItineraryTimeline,
  NodeResponse,
} from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

// The node as the store holds it: resolved under the OLD (undated) anchor.
const STALE_NODE: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "pending",
  title: "Dion Archaeological Park",
  source: null,
  source_id: null,
  metadata: { start_time: "2026-07-21T10:00:00+03:00", duration_minutes: 90 },
};

// A client-only node (an accepted proposal the fetch may race) — must survive.
const LOCAL_ONLY: NodeResponse = {
  ...STALE_NODE,
  id: "n-local",
  title: "Just accepted",
  metadata: { start_time: "2026-07-22T09:00:00+03:00" },
};

function itineraryRow(overrides: Partial<ItineraryResponse>): ItineraryResponse {
  return {
    id: "it-1",
    title: "Mount Olympus by First Light",
    client_id: "c-1",
    created_by: "u-1",
    display_status: "in_studio",
    forked_from_id: "trunk-1",
    ...overrides,
  } as ItineraryResponse;
}

function staleTimeline(): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 3,
    windowStart: "2026-07-21T00:00:00+03:00",
    windowEnd: "2026-07-22T23:59:00+03:00",
    days: [
      { date: "2026-07-21", label: "Day 1" },
      { date: "2026-07-22", label: "Day 2" },
    ],
    itinerary: itineraryRow({}),
    nodes: [STALE_NODE, LOCAL_ONLY],
    edges: [],
  };
}

// The server's re-read after the agent set real dates: same node re-resolved
// onto the new anchor, plus a node the store hasn't been shown yet.
const FRESH_RESULT = {
  ok: true as const,
  itinerary: itineraryRow({
    timing_kind: "exact",
    date_start: "2026-08-17",
    date_end: "2026-08-19",
    anchor_date: "2026-08-17",
  }),
  nodes: [
    {
      ...STALE_NODE,
      metadata: { start_time: "2026-08-18T10:00:00+03:00", duration_minutes: 90 },
    },
    {
      ...STALE_NODE,
      id: "n-server-only",
      title: "Not yet revealed",
      metadata: { start_time: "2026-08-19T09:00:00+03:00", duration_minutes: 60 },
    },
  ],
  edges: [],
  totals: { EUR: "1200.00" },
  display_currency: "USD",
  total_display: "1300.00",
  party_size: 2,
  viewer_open_fork_id: null,
  findings: [],
  nightly_lodging: [{ day_index: 2, on: "2026-08-18", node_id: "n1" }],
};

function renderStore() {
  const init: ItineraryGraphInit = {
    timeline: staleTimeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: "http://api",
    accessToken: "token",
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      {children}
    </itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("refetchGraph", () => {
  test("re-anchors resolved schedules, keeps local-only nodes, skips server-only ones", async () => {
    vi.mocked(getItinerary).mockResolvedValue(FRESH_RESULT as never);
    const { result } = renderStore();

    await act(async () => {
      result.current.getState().refetchGraph();
    });

    const s = result.current.getState();
    // The known node adopted the server's re-resolved start.
    const n1 = s.nodes.find((n) => n.id === "n1");
    expect((n1?.metadata as { start_time?: string }).start_time).toBe(
      "2026-08-18T10:00:00+03:00",
    );
    // The client-only node survived the merge untouched.
    expect(s.nodes.some((n) => n.id === "n-local")).toBe(true);
    // The server-only node was NOT injected (its node_created frame owns that).
    expect(s.nodes.some((n) => n.id === "n-server-only")).toBe(false);
    // `sample` re-anchored: day-index conversion for drops uses the new dates.
    expect(s.sample.days[0]?.date).toBe("2026-08-17");
    expect(s.sample.dayOneKey).toBe("2026-08-17");
    // Night coverage + money followed the fresh read.
    expect(s.nightlyLodging).toEqual(FRESH_RESULT.nightly_lodging);
    expect(s.totals).toEqual({ EUR: "1200.00" });
    expect(s.displayCurrency).toBe("USD");
    expect(s.totalDisplay).toBe("1300.00");
  });

  test("no-ops without credentials and on a failed read", async () => {
    vi.mocked(getItinerary).mockResolvedValue({
      ok: false,
      status: 500,
      detail: "unknown",
    } as never);
    const { result } = renderStore();
    const before = result.current.getState().nodes;

    await act(async () => {
      result.current.getState().refetchGraph();
    });

    expect(result.current.getState().nodes).toBe(before);
  });
});
