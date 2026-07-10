// The Collection rail: shows the unscheduled "maybes" by default (a placed node
// is hidden until the "Scheduled" toggle reveals it — the timeline is where it
// lives now), drops discarded nodes, groups the rest along a switchable axis,
// and offers link/note add affordances.
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
  deleteNode: vi.fn(async () => ({ ok: true })),
}));

import { createNode, createNodeFromLink, deleteNode } from "@ov-black/api-client";
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
  display_status: "in_studio",
};

function node(id: string, over: Partial<NodeResponse> = {}): NodeResponse {
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
    status: "in_studio",
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
  const cardIds = () =>
    screen
      .getAllByTestId("collection-card")
      .map((c) => c.getAttribute("data-node-id"));

  test("hides placed nodes by default; the Scheduled toggle reveals them", () => {
    renderRail([
      node("wish", { type: "experience" }),
      node("scheduled", {
        type: "meal",
        metadata: { start_time: "2024-06-20T12:00:00+09:00" },
      }),
      node("gone", { type: "hotel", status: "discarded" }),
    ]);
    // Default: only the unscheduled maybe; the placed card is out of the way and
    // the discarded one is gone entirely.
    expect(cardIds()).toEqual(["wish"]);

    // The toggle counts the hidden placed cards; clicking it brings them back.
    fireEvent.click(screen.getByTestId("collection-show-scheduled"));
    const ids = cardIds();
    expect(ids).toContain("wish");
    expect(ids).toContain("scheduled");
    expect(ids).not.toContain("gone");
    // The revealed card is marked as already on the timeline.
    const placed = screen
      .getAllByTestId("collection-card")
      .find((c) => c.getAttribute("data-node-id") === "scheduled");
    expect(placed?.getAttribute("data-scheduled")).toBe("true");
  });

  test("no Scheduled toggle when nothing is placed", () => {
    renderRail([node("wish", { type: "experience" })]);
    expect(screen.queryByTestId("collection-show-scheduled")).toBeNull();
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

describe("CollectionRail · remove", () => {
  test("a non-firmed maybe offers a remove control that soft-deletes it", () => {
    renderRail([node("wish", { type: "experience", status: "pending" })]);
    fireEvent.click(screen.getByTestId("collection-remove"));
    expect(deleteNode).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ itineraryId: "it-1", nodeId: "wish" }),
    );
  });

  test("a firmed card offers no remove control (demote before delete)", () => {
    renderRail([
      node("firm", { status: "approved", lock_reason: "status_locked" }),
    ]);
    expect(screen.queryByTestId("collection-remove")).toBeNull();
    expect(deleteNode).not.toHaveBeenCalled();
  });

  test("a viewer without credentials gets no remove control", () => {
    renderRail([node("wish", { type: "experience" })], {
      accessToken: null,
    });
    expect(screen.queryByTestId("collection-remove")).toBeNull();
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
