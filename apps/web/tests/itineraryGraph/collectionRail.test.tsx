// The Collection rail: shows every non-discarded node (a placed node stays in
// the wish list — the timeline is an extra surface, not a move out), groups
// them along a switchable axis, and offers link/note add affordances.
// The api-client wrappers are mocked so writes are asserted without a backend.

import { DndContext } from "@dnd-kit/core";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const SAVED_NODE = {
  id: "saved-1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "note",
  status: "proposed",
  title: "saved",
  source: null,
  source_id: null,
  metadata: {},
};

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  createNode: vi.fn(async () => ({ ok: true, node: SAVED_NODE })),
  createNodeFromLink: vi.fn(async () => ({ ok: true, node: SAVED_NODE })),
  updateNode: vi.fn(async () => ({ ok: true })),
}));

import { createNode, createNodeFromLink } from "@ov-black/api-client";
import type {
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { CollectionRail } from "@/app/_components/itinerary-graph/collection/CollectionRail";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

function node(id: string, over: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "proposed",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...over,
  };
}

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

function renderRail(nodes: NodeResponse[], partial: Partial<ItineraryGraphInit> = {}) {
  const init: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "draft",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      <DndContext>{children}</DndContext>
    </itineraryGraphStore.Provider>
  );
  return render(<CollectionRail variant="board" />, { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("CollectionRail · filtering", () => {
  test("keeps placed nodes and drops only discarded ones", () => {
    renderRail([
      node("wish", { type: "experience" }),
      node("scheduled", {
        type: "meal",
        metadata: { start_time: "2024-06-20T12:00:00+09:00" },
      }),
      node("gone", { type: "hotel", status: "discarded" }),
    ]);
    const ids = screen
      .getAllByTestId("collection-card")
      .map((c) => c.getAttribute("data-node-id"));
    // The placed (scheduled) node STAYS in the wish list; only discarded leaves.
    expect(ids).toHaveLength(2);
    expect(ids).toContain("wish");
    expect(ids).toContain("scheduled");
    expect(ids).not.toContain("gone");
  });

  test("renders the empty state only when every node is discarded", () => {
    renderRail([node("gone", { status: "discarded" })]);
    expect(screen.getByTestId("collection-empty")).toBeInTheDocument();
    expect(screen.queryAllByTestId("collection-card")).toHaveLength(0);
  });
});

describe("CollectionRail · grouping", () => {
  test("switching the axis re-groups the same items", () => {
    renderRail([
      node("m", { type: "meal" }),
      node("e", { type: "experience" }),
    ]);
    // Default: by type → two named lanes.
    let lanes = screen.getAllByTestId("collection-lane").map((l) => l.dataset["lane"]);
    expect(lanes).toContain("eat");
    expect(lanes).toContain("do");

    fireEvent.click(screen.getByTestId("collection-groupby-cost"));
    lanes = screen.getAllByTestId("collection-lane").map((l) => l.dataset["lane"]);
    // Neither carries a cost → both fall into the single "No price" lane. (The
    // by-type lanes may briefly linger under AnimatePresence exit in jsdom, so
    // assert the new cost lane appeared rather than exact equality.)
    expect(lanes).toContain("cnone");
    const cnone = screen
      .getAllByTestId("collection-lane")
      .find((l) => l.dataset["lane"] === "cnone");
    expect(within(cnone!).getAllByTestId("collection-card")).toHaveLength(2);
  });
});

describe("CollectionRail · add affordances", () => {
  test("pasting a link saves it via createNodeFromLink", () => {
    renderRail([]);
    const input = screen.getByTestId("collection-add-link");
    fireEvent.change(input, { target: { value: "https://kikunoi.jp/" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(createNodeFromLink).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ itineraryId: "it-1", url: "https://kikunoi.jp/" }),
    );
  });

  test("jotting a note creates a timeless note", () => {
    renderRail([]);
    const input = screen.getByTestId("collection-add-note");
    fireEvent.change(input, { target: { value: "sushi counter, not a table" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(createNode).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        itineraryId: "it-1",
        body: expect.objectContaining({ type: "note", title: "sushi counter, not a table" }),
      }),
    );
  });
});
