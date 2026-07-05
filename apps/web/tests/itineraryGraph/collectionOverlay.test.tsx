// The Collection overlay (M006/PS6): the wish list summoned as a LAYER over the
// timeline for pick-then-place. Asserts the summon → drawer → close/Esc cycle and
// that holding a card (place mode) auto-dismisses the drawer so the timeline
// tap targets show underneath.

import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useParams: () => ({ id: "it-1" }),
}));

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
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { CollectionOverlay } from "@/app/itinerary/[id]/_shell/CollectionOverlay";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

const NODE: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "proposed",
  title: "Sushi Saito",
  source: null,
  source_id: null,
  metadata: {},
};

function timeline(): ItineraryTimeline {
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
    nodes: [NODE],
    edges: [],
  };
}

function renderOverlay() {
  const init: ItineraryGraphInit = {
    timeline: timeline(),
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
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      <Capture />
      {children}
    </itineraryGraphStore.Provider>
  );
  render(<CollectionOverlay />, { wrapper });
  return () => api!;
}

describe("CollectionOverlay", () => {
  test("summon opens the drawer; Close and Esc dismiss it", () => {
    renderOverlay();
    expect(screen.queryByTestId("collection-overlay")).toBeNull();

    fireEvent.click(screen.getByTestId("collection-summon"));
    const drawer = screen.getByTestId("collection-overlay");
    // The wish-list card is inside the drawer.
    expect(drawer).toHaveTextContent("Sushi Saito");
    // Focus moves into the drawer (a11y) — the Close button receives it.
    expect(screen.getByTestId("collection-overlay-close")).toHaveFocus();

    fireEvent.click(screen.getByTestId("collection-overlay-close"));
    expect(screen.queryByTestId("collection-overlay")).toBeNull();

    // Reopen, then Esc.
    fireEvent.click(screen.getByTestId("collection-summon"));
    expect(screen.getByTestId("collection-overlay")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("collection-overlay")).toBeNull();
  });

  test("holding a card auto-closes the drawer and hides the summon", () => {
    const getApi = renderOverlay();
    fireEvent.click(screen.getByTestId("collection-summon"));
    expect(screen.getByTestId("collection-overlay")).toBeInTheDocument();

    // Place mode starts → the drawer clears so the timeline targets are visible,
    // and the summon hides (you're mid-placement, not picking).
    act(() => getApi().getState().holdItem("n1"));
    expect(screen.queryByTestId("collection-overlay")).toBeNull();
    expect(screen.queryByTestId("collection-summon")).toBeNull();
  });
});
