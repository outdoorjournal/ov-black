// Traveler write paths with credentials present: leaving an attached note,
// branching an alternative, asking staff to merge, and persisting a drag-move
// on the traveler's own alternative. The api-client wrappers are mocked.

import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  acquireItineraryLock: vi.fn(async () => ({ ok: true })),
  releaseItineraryLock: vi.fn(async () => ({ ok: true })),
  approveItinerary: vi.fn(async () => ({ ok: true })),
  createNode: vi.fn(async () => ({
    ok: true,
    node: { id: "server-note", type: "note" },
  })),
  deleteNode: vi.fn(async () => ({ ok: true })),
  updateNode: vi.fn(async () => ({ ok: true, node: { id: "n1" } })),
  createNodeFromInventory: vi.fn(),
  searchInventory: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysis: vi.fn(),
  fillGap: vi.fn(),
  forkItinerary: vi.fn(async () => ({
    ok: true,
    graph: { itinerary: { id: "fork-9" }, nodes: [], edges: [] },
  })),
  requestReconcile: vi.fn(async () => ({ ok: true, itinerary: { id: "fork-9" } })),
}));

import {
  createNode,
  forkItinerary,
  requestReconcile,
  updateNode,
  type EdgeResponse,
  type ItineraryResponse,
  type NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

const HOST: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "proposed",
  title: "Tea at 1:30",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T13:30:00+09:00", duration_minutes: 60 },
};

function timeline(forkedFromId: string | null): ItineraryTimeline {
  const itinerary: ItineraryResponse = {
    id: "it-1",
    title: "Trip",
    client_id: "c-1",
    created_by: "u-1",
    status: "draft",
    forked_from_id: forkedFromId,
  };
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary,
    nodes: [HOST],
    edges: [] as EdgeResponse[],
  };
}

function renderStore(forkedFromId: string | null) {
  const init: ItineraryGraphInit = {
    timeline: timeline(forkedFromId),
    itineraryId: "it-1",
    status: "draft",
    role: "client",
    apiBaseUrl: "http://api",
    accessToken: "token",
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>{children}</itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("traveler notes", () => {
  test("addAttachedNote optimistically adds a note and POSTs it", () => {
    const { result } = renderStore(null);
    act(() => result.current.getState().addAttachedNote("n1", "why 1:30?"));
    const added = result.current
      .getState()
      .nodes.find((n) => n.type === "note");
    expect(added?.attached_to_node_id).toBe("n1");
    expect(added?.title).toBe("why 1:30?");
    expect(createNode).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        itineraryId: "it-1",
        body: expect.objectContaining({
          type: "note",
          attached_to_node_id: "n1",
          title: "why 1:30?",
        }),
      }),
    );
  });
});

describe("alternative lifecycle", () => {
  test("createAlternative forks and hands back the new fork id", async () => {
    const { result } = renderStore(null);
    const onForked = vi.fn();
    await act(async () => {
      result.current.getState().createAlternative(onForked);
      await Promise.resolve();
    });
    expect(forkItinerary).toHaveBeenCalledWith(expect.anything(), "it-1");
    expect(onForked).toHaveBeenCalledWith("fork-9");
  });

  test("requestMerge asks staff and marks the request sent", async () => {
    const { result } = renderStore("base-1");
    await act(async () => {
      result.current.getState().requestMerge();
      await Promise.resolve();
    });
    expect(requestReconcile).toHaveBeenCalled();
    expect(result.current.getState().mergeRequested).toBe(true);
  });
});

describe("traveler drag-move persists only on an alternative", () => {
  test("on the agreed plan (not a fork) a move is optimistic but not persisted", () => {
    const { result } = renderStore(null);
    act(() => result.current.getState().moveNode("n1", "2024-06-20", 600));
    expect(updateNode).not.toHaveBeenCalled();
  });

  test("on the traveler's own alternative a move is persisted", () => {
    const { result } = renderStore("base-1");
    act(() => result.current.getState().moveNode("n1", "2024-06-20", 600));
    expect(updateNode).toHaveBeenCalled();
  });
});
