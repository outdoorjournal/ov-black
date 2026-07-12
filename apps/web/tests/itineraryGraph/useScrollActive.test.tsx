// The scroll-active pin's reflow guard. A click-pin must survive a PROGRAMMATIC
// reflow (a re-time/edit from the rail re-sorts the spine and can shove the
// pinned card out of the center band with no scroll) — the observer only hands
// focus back to scroll once the USER has actually scrolled since pinning. Drives
// the IntersectionObserver directly (jsdom has none) to script band occupancy.

import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useScrollActive } from "@/app/_components/itinerary-graph/views/journal/useScrollActive";

// ── IntersectionObserver harness ──────────────────────────────────────────────
type IOEntry = {
  target: Element;
  isIntersecting: boolean;
  intersectionRatio: number;
};
let ioCallback: ((entries: IOEntry[]) => void) | null = null;
function fireIO(entries: IOEntry[]) {
  act(() => ioCallback!(entries));
}

class MockIO {
  constructor(cb: (entries: IOEntry[]) => void) {
    ioCallback = cb;
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

// ── Store harness ─────────────────────────────────────────────────────────────
const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
};

function node(id: string): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
  };
}

function renderScrollActive() {
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
      nodes: [node("a"), node("b")],
      edges: [],
    } satisfies ItineraryTimeline,
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: null,
    accessToken: null,
  };
  let api: ReturnType<typeof itineraryGraphStore.useStoreApi> | null = null;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      {children}
    </itineraryGraphStore.Provider>
  );
  const { result } = renderHook(
    () => {
      api = itineraryGraphStore.useStoreApi();
      return useScrollActive({});
    },
    { wrapper },
  );
  // Register two card rows so the observer can attribute ratios to a/b.
  const elA = document.createElement("div");
  const elB = document.createElement("div");
  act(() => {
    result.current("a")(elA);
    result.current("b")(elB);
  });
  return { api: api!, elA, elB };
}

beforeEach(() => {
  ioCallback = null;
  vi.stubGlobal("IntersectionObserver", MockIO);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("scroll-active pin — reflow guard", () => {
  test("a click-pin survives a reflow that pushes it out of the band (no scroll)", () => {
    const { api, elA, elB } = renderScrollActive();
    act(() => api.getState().focusNode("a", "click"));

    // A holds the band → pinned, obviously.
    fireIO([{ target: elA, isIntersecting: true, intersectionRatio: 0.6 }]);
    expect(api.getState().focusedNodeId).toBe("a");

    // Reflow: A leaves the band, B slides in — but the user never scrolled.
    fireIO([
      { target: elA, isIntersecting: false, intersectionRatio: 0 },
      { target: elB, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    // The pin holds — the panel does NOT swap to B.
    expect(api.getState().focusedNodeId).toBe("a");
    expect(api.getState().focusSource).toBe("click");
  });

  test("once the user scrolls, the pin yields to the banded card", () => {
    const { api, elA, elB } = renderScrollActive();
    act(() => api.getState().focusNode("a", "click"));
    fireIO([{ target: elA, isIntersecting: true, intersectionRatio: 0.6 }]);

    // A real scroll arms release…
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    fireIO([
      { target: elA, isIntersecting: false, intersectionRatio: 0 },
      { target: elB, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    expect(api.getState().focusedNodeId).toBe("b");
    expect(api.getState().focusSource).toBe("scroll");
  });

  test("a hard focus lock stands the observer fully down (even after a scroll)", () => {
    const { api, elA, elB } = renderScrollActive();
    act(() => api.getState().focusNode("a", "click"));
    // Expand-to-lock: the 2xl inline detail is open on A.
    act(() => api.getState().setFocusLocked(true));

    // Even a real scroll that pushes A out and B in must not move focus.
    act(() => window.dispatchEvent(new Event("scroll")));
    fireIO([
      { target: elA, isIntersecting: false, intersectionRatio: 0 },
      { target: elB, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    expect(api.getState().focusedNodeId).toBe("a");

    // Releasing the lock hands control back to scroll observation.
    act(() => api.getState().setFocusLocked(false));
    fireIO([
      { target: elA, isIntersecting: false, intersectionRatio: 0 },
      { target: elB, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    expect(api.getState().focusedNodeId).toBe("b");
  });

  test("a fresh click-pin re-arms the guard (a prior scroll doesn't leak)", () => {
    const { api, elA, elB } = renderScrollActive();
    // Pin A, scroll away to B (source scroll).
    act(() => api.getState().focusNode("a", "click"));
    act(() => window.dispatchEvent(new Event("scroll")));
    fireIO([
      { target: elA, isIntersecting: false, intersectionRatio: 0 },
      { target: elB, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    expect(api.getState().focusedNodeId).toBe("b");

    // Now click-pin B, then reflow it out of the band without scrolling.
    act(() => api.getState().focusNode("b", "click"));
    fireIO([
      { target: elB, isIntersecting: false, intersectionRatio: 0 },
      { target: elA, isIntersecting: true, intersectionRatio: 0.6 },
    ]);
    // The new pin holds — the earlier scroll must not still be arming release.
    expect(api.getState().focusedNodeId).toBe("b");
    expect(api.getState().focusSource).toBe("click");
  });
});
