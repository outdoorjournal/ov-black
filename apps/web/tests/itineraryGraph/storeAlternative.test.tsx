// Traveler two-version (Official ↔ My version) write paths with credentials
// present: leaving an attached note (never forks), switching versions, the lazy
// fork-on-first-edit, asking staff to merge, cancelling that request, discarding
// the version, and persisting a drag-move on a real fork. api-client mocked.

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
    graph: {
      itinerary: { id: "fork-9", forked_from_id: "it-1" },
      // The fork node paired to baseline node "n1" by lineage.
      nodes: [{ id: "fork-n1", forked_from_node_id: "n1" }],
      edges: [],
    },
  })),
  requestReconcile: vi.fn(async () => ({ ok: true, itinerary: { id: "fork-9" } })),
  cancelReconcile: vi.fn(async () => ({ ok: true, itinerary: { id: "fork-9" } })),
  abandonFork: vi.fn(async () => ({ ok: true, itinerary: { id: "fork-9" } })),
}));

import {
  abandonFork,
  cancelReconcile,
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

function renderStore(
  forkedFromId: string | null,
  viewerOpenForkId: string | null = null,
) {
  const init: ItineraryGraphInit = {
    timeline: timeline(forkedFromId),
    itineraryId: "it-1",
    status: "draft",
    role: "client",
    apiBaseUrl: "http://api",
    accessToken: "token",
    viewerOpenForkId,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>{children}</itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("traveler notes", () => {
  test("addAttachedNote optimistically adds a note and POSTs it — never forks", () => {
    const { result } = renderStore(null);
    act(() => result.current.getState().addAttachedNote("n1", "why 1:30?"));
    const added = result.current
      .getState()
      .nodes.find((n) => n.type === "note");
    expect(added?.attached_to_node_id).toBe("n1");
    expect(added?.title).toBe("why 1:30?");
    // Leaving a note works on either version and must NOT branch a fork.
    expect(forkItinerary).not.toHaveBeenCalled();
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

describe("selectVersion (two-version toggle)", () => {
  test("on Official with no fork yet, switching to mine enters draft-mine (no navigation)", () => {
    const { result } = renderStore(null);
    const nav = vi.fn();
    act(() => result.current.getState().selectVersion("mine", nav));
    expect(result.current.getState().draftMine).toBe(true);
    expect(nav).not.toHaveBeenCalled();
  });

  test("on Official with an existing fork, switching to mine navigates to it", () => {
    const { result } = renderStore(null, "fork-existing");
    const nav = vi.fn();
    act(() => result.current.getState().selectVersion("mine", nav));
    expect(nav).toHaveBeenCalledWith("fork-existing");
    expect(result.current.getState().draftMine).toBe(false);
  });

  test("on a fork, switching to official navigates to the baseline", () => {
    const { result } = renderStore("base-1");
    const nav = vi.fn();
    act(() => result.current.getState().selectVersion("official", nav));
    expect(nav).toHaveBeenCalledWith("base-1");
  });

  test("switching back to official from draft-mine just clears draft mode", () => {
    const { result } = renderStore(null);
    const nav = vi.fn();
    act(() => result.current.getState().selectVersion("mine", nav));
    act(() => result.current.getState().selectVersion("official", nav));
    expect(result.current.getState().draftMine).toBe(false);
    expect(nav).not.toHaveBeenCalled();
  });
});

describe("lazy fork on first edit (forkAndMove)", () => {
  test("draft-mine drag forks, carries the move onto the fork node, then navigates", async () => {
    const { result } = renderStore(null);
    const nav = vi.fn();
    act(() => result.current.getState().selectVersion("mine", nav));
    await act(async () => {
      result.current.getState().forkAndMove("n1", "2024-06-20", 600, nav);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(forkItinerary).toHaveBeenCalledWith(expect.anything(), "it-1");
    // The move is carried onto the lineage-paired fork node, not the baseline.
    expect(updateNode).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ itineraryId: "fork-9", nodeId: "fork-n1" }),
    );
    expect(nav).toHaveBeenCalledWith("fork-9");
  });

  test("forkAndMove is a no-op when not in draft-mine", () => {
    const { result } = renderStore(null); // draftMine false
    const nav = vi.fn();
    act(() => result.current.getState().forkAndMove("n1", "2024-06-20", 600, nav));
    expect(forkItinerary).not.toHaveBeenCalled();
  });
});

describe("merge request lifecycle", () => {
  test("requestMerge asks staff and marks the request sent", async () => {
    const { result } = renderStore("base-1");
    await act(async () => {
      result.current.getState().requestMerge();
      await Promise.resolve();
    });
    expect(requestReconcile).toHaveBeenCalled();
    expect(result.current.getState().mergeRequested).toBe(true);
  });

  test("cancelMerge withdraws the request and the fork stays (mergeRequested false)", async () => {
    const { result } = renderStore("base-1");
    await act(async () => {
      result.current.getState().requestMerge();
      await Promise.resolve();
    });
    await act(async () => {
      result.current.getState().cancelMerge();
      await Promise.resolve();
    });
    expect(cancelReconcile).toHaveBeenCalled();
    expect(result.current.getState().mergeRequested).toBe(false);
  });

  test("discardMine abandons the fork and navigates back to Official", async () => {
    const { result } = renderStore("base-1");
    const nav = vi.fn();
    await act(async () => {
      result.current.getState().discardMine(nav);
      await Promise.resolve();
    });
    expect(abandonFork).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith("base-1");
  });
});

describe("traveler drag-move persists only on a real fork", () => {
  test("on the official plan (not a fork, not draft-mine) a move is optimistic but not persisted", () => {
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
