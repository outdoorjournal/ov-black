// The Journal's focus provenance (phase 1 scroll-active system): `focusNode`
// records HOW a node became focused so a deliberate click-pin outranks ambient
// scroll observation, and the rail's idle state survives the store's seeded
// default focus (focusSource starts null).

import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
};

const NODE: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "pending",
  title: "Tea ceremony",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
};

function renderStore() {
  const init: ItineraryGraphInit = {
    timeline: {
      id: "it-1",
      label: "Trip",
      subtitle: "",
      mood: "verdant",
      timezoneOffsetHours: 9,
      windowStart: "2024-06-20T00:00:00+09:00",
      windowEnd: "2024-06-20T23:59:00+09:00",
      days: [{ date: "2024-06-20", label: "Day 1" }],
      itinerary: ITINERARY,
      nodes: [NODE],
      edges: [],
    } satisfies ItineraryTimeline,
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: null,
    accessToken: null,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      {children}
    </itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

describe("focusSource", () => {
  test("starts null — a seeded default focus is not an interaction", () => {
    const { result } = renderStore();
    expect(result.current.getState().focusSource).toBeNull();
  });

  test("focusNode defaults to a click pin; scroll is explicit", () => {
    const { result } = renderStore();
    act(() => result.current.getState().focusNode("n1"));
    expect(result.current.getState().focusSource).toBe("click");

    act(() => result.current.getState().focusNode("n1", "scroll"));
    expect(result.current.getState().focusSource).toBe("scroll");
  });

  test("clearing focus clears the source", () => {
    const { result } = renderStore();
    act(() => result.current.getState().focusNode("n1", "click"));
    act(() => result.current.getState().focusNode(null));
    expect(result.current.getState().focusedNodeId).toBeNull();
    expect(result.current.getState().focusSource).toBeNull();
  });

  test("a hard lock survives re-focusing the same node but clears on another", () => {
    const { result } = renderStore();
    act(() => result.current.getState().focusNode("n1", "click"));
    act(() => result.current.getState().setFocusLocked(true));
    expect(result.current.getState().focusLocked).toBe(true);

    // Re-focusing the SAME node (e.g. a scroll re-assert) keeps the lock.
    act(() => result.current.getState().focusNode("n1", "scroll"));
    expect(result.current.getState().focusLocked).toBe(true);

    // Moving to ANOTHER node is a deliberate switch — the lock releases.
    act(() => result.current.getState().focusNode("n2", "click"));
    expect(result.current.getState().focusLocked).toBe(false);
  });
});
