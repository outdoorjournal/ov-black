// Place mode (M006/PS5): pick-then-place scheduling as a non-drag path. These
// cover the three moving parts — the store's held/place/undo slice, the
// Collection card's Schedule affordance, and the shell's PlaceModeLayer (holding
// chip · Esc · undo toast · slide-to-timeline). The canvas tap TARGETS need real
// layout geometry, so they're left to e2e; here we assert the wiring around them.

import { DndContext } from "@dnd-kit/core";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const nav = vi.hoisted(() => ({ pathname: "/itinerary/it-1/collection" }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => nav.pathname,
}));

// The rail card uses @ov-black/api-client for its add affordances; stub it so the
// store's updateNode persistence in placeHeldItem is a no-op under test.
vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  updateNode: vi.fn(async () => ({ ok: true })),
  createNode: vi.fn(async () => ({ ok: true })),
  createNodeFromLink: vi.fn(async () => ({ ok: true })),
}));

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  selectCanSchedule,
  type ItineraryGraphInit,
  type ItineraryGraphState,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { CollectionRail } from "@/app/_components/itinerary-graph/collection/CollectionRail";
import { PlaceModeLayer } from "@/app/itinerary/[id]/_shell/PlaceModeLayer";

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
    title: id === "n1" ? "Sushi Saito" : id,
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

function storeApiHook(init: Partial<ItineraryGraphInit> = {}, nodes: NodeResponse[] = [node("n1")]) {
  const full: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "draft",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    startLocked: true,
    ...init,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={full}>{children}</itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

beforeEach(() => {
  nav.pathname = "/itinerary/it-1/collection";
  push.mockClear();
});

describe("store · place-mode slice", () => {
  test("holdItem lifts a card; placeHeldItem moves it + records the placement", () => {
    const { result } = storeApiHook();
    act(() => result.current.getState().holdItem("n1"));
    expect(result.current.getState().heldItem).toEqual({ nodeId: "n1", title: "Sushi Saito" });

    act(() => result.current.getState().placeHeldItem("2024-06-20", 600));
    const s = result.current.getState();
    expect(s.heldItem).toBeNull();
    expect(s.lastPlacement).toEqual({
      nodeId: "n1",
      title: "Sushi Saito",
      dayKey: "2024-06-20",
      minute: 600,
    });
    // moveNode rebased the node onto 10:00 that day.
    const moved = s.nodes.find((n) => n.id === "n1");
    expect((moved?.metadata as { start_time?: string }).start_time).toContain("T10:00");
  });

  test("placeHeldItem is inert (no placement) for a viewer who can't schedule", () => {
    const { result } = storeApiHook({ role: "client", startLocked: false });
    act(() => result.current.getState().holdItem("n1"));
    act(() => result.current.getState().placeHeldItem("2024-06-20", 600));
    const s = result.current.getState();
    expect(s.heldItem).toBeNull(); // the hold is dropped
    expect(s.lastPlacement).toBeNull(); // but nothing was scheduled
  });

  test("undoPlacement returns the card to the Collection", () => {
    const { result } = storeApiHook();
    act(() => result.current.getState().holdItem("n1"));
    act(() => result.current.getState().placeHeldItem("2024-06-20", 600));
    act(() => result.current.getState().undoPlacement());
    const s = result.current.getState();
    expect(s.lastPlacement).toBeNull();
    // unscheduleNode cleared the start_time, so it's a Collection item again.
    expect((s.nodes.find((n) => n.id === "n1")?.metadata as { start_time?: string }).start_time).toBeUndefined();
  });

  test("holding supersedes a lingering undo toast", () => {
    const { result } = storeApiHook();
    act(() => result.current.getState().holdItem("n1"));
    act(() => result.current.getState().placeHeldItem("2024-06-20", 600));
    expect(result.current.getState().lastPlacement).not.toBeNull();
    act(() => result.current.getState().holdItem("n1"));
    expect(result.current.getState().lastPlacement).toBeNull();
  });

  test("selectCanSchedule: advisor-with-lock yes, plain traveler no", () => {
    expect(
      selectCanSchedule({ canEdit: true, lockStatus: "locked-by-me", status: "draft" } as ItineraryGraphState),
    ).toBe(true);
    expect(
      selectCanSchedule({
        canEdit: false,
        status: "draft",
        apiBaseUrl: "x",
        accessToken: "y",
        sample: { itinerary: {} },
      } as unknown as ItineraryGraphState),
    ).toBe(false);
  });
});

describe("CollectionRail · Schedule affordance", () => {
  function renderRail(partial: Partial<ItineraryGraphInit>) {
    const init: ItineraryGraphInit = {
      timeline: timeline([node("n1")]),
      itineraryId: "it-1",
      status: "draft",
      role: "advisor",
      apiBaseUrl: "http://api.test",
      accessToken: "tok",
      startLocked: true,
      ...partial,
    };
    let api: ReturnType<typeof itineraryGraphStore.useStoreApi> | null = null;
    function Capture() {
      api = itineraryGraphStore.useStoreApi();
      return null;
    }
    render(
      <itineraryGraphStore.Provider initial={init}>
        <Capture />
        <DndContext>
          <CollectionRail variant="board" />
        </DndContext>
      </itineraryGraphStore.Provider>,
    );
    return () => api;
  }

  test("an editable viewer gets Schedule; clicking it holds the card", () => {
    const getApi = renderRail({ role: "advisor", startLocked: true });
    const btn = screen.getByTestId("collection-schedule");
    fireEvent.click(btn);
    expect(getApi()?.getState().heldItem).toEqual({ nodeId: "n1", title: "Sushi Saito" });
  });

  test("a read-only viewer never sees Schedule", () => {
    renderRail({ role: "client", startLocked: false });
    expect(screen.queryByTestId("collection-schedule")).toBeNull();
  });
});

describe("PlaceModeLayer · cross-surface chrome", () => {
  function renderLayer(nodes: NodeResponse[] = [node("n1")]) {
    const init: ItineraryGraphInit = {
      timeline: timeline(nodes),
      itineraryId: "it-1",
      status: "draft",
      role: "advisor",
      apiBaseUrl: "http://api.test",
      accessToken: "tok",
      startLocked: true,
    };
    let api: ReturnType<typeof itineraryGraphStore.useStoreApi> | null = null;
    function Capture() {
      api = itineraryGraphStore.useStoreApi();
      return null;
    }
    render(
      <itineraryGraphStore.Provider initial={init}>
        <TimelineDataProvider value={{ timeline: timeline(nodes), baselineTitle: null }}>
          <Capture />
          <PlaceModeLayer />
        </TimelineDataProvider>
      </itineraryGraphStore.Provider>,
    );
    return () => api!;
  }

  test("holding shows the chip and slides over to the timeline; Esc cancels", () => {
    const getApi = renderLayer();
    expect(screen.queryByTestId("holding-chip")).toBeNull();

    act(() => getApi().getState().holdItem("n1"));
    const chip = screen.getByTestId("holding-chip");
    expect(chip).toHaveTextContent("Sushi Saito");
    // Not on the timeline (pathname=collection) → slide over to it.
    expect(push).toHaveBeenCalledWith("/itinerary/it-1/timeline");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("holding-chip")).toBeNull();
  });

  test("does not re-navigate when already on the timeline", () => {
    nav.pathname = "/itinerary/it-1/timeline";
    const getApi = renderLayer();
    act(() => getApi().getState().holdItem("n1"));
    expect(push).not.toHaveBeenCalled();
  });

  test("a placement shows the undo toast; Undo returns the card to the Collection", () => {
    const getApi = renderLayer();
    act(() => getApi().getState().holdItem("n1"));
    act(() => getApi().getState().placeHeldItem("2024-06-20", 840));

    const toast = screen.getByTestId("place-toast");
    expect(toast).toHaveTextContent("Added to Day 1 · 14:00");

    fireEvent.click(screen.getByTestId("place-undo"));
    expect(screen.queryByTestId("place-toast")).toBeNull();
    expect(getApi().getState().lastPlacement).toBeNull();
  });
});
