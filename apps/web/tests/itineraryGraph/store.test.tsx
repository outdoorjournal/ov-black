// Tests for the view-agnostic itinerary graph store: the editable gate and the
// safety property that editing actions are inert for non-staff / no-credential
// viewers (so a traveler can never mutate, even if an action is invoked).

import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";

import type {
  EdgeResponse,
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  selectEditable,
  type ItineraryGraphInit,
  type ItineraryGraphState,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

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
  type: "note",
  status: "approved",
  title: "Original",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
};

function timeline(nodes: NodeResponse[], edges: EdgeResponse[] = []): ItineraryTimeline {
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
    edges,
  };
}

function renderStore(init: Partial<ItineraryGraphInit> = {}) {
  const full: ItineraryGraphInit = {
    timeline: timeline([NODE]),
    itineraryId: "it-1",
    status: "draft",
    role: "client",
    apiBaseUrl: null,
    accessToken: null,
    ...init,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={full}>
      {children}
    </itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

describe("selectEditable", () => {
  const base = { status: "draft", lockStatus: "locked-by-me" } as ItineraryGraphState;
  test("requires canEdit", () => {
    expect(selectEditable({ ...base, canEdit: false } as ItineraryGraphState)).toBe(false);
  });
  test("requires the lock held by self", () => {
    expect(
      selectEditable({ ...base, canEdit: true, lockStatus: "unlocked" } as ItineraryGraphState),
    ).toBe(false);
    expect(
      selectEditable({ ...base, canEdit: true, lockStatus: "locked-by-other" } as ItineraryGraphState),
    ).toBe(false);
  });
  test("requires a draft (not approved)", () => {
    expect(
      selectEditable({ ...base, canEdit: true, status: "approved" } as ItineraryGraphState),
    ).toBe(false);
  });
  test("true only when staff + locked-by-me + draft", () => {
    expect(selectEditable({ ...base, canEdit: true } as ItineraryGraphState)).toBe(true);
  });
});

describe("editing actions are inert for non-editable viewers", () => {
  test("traveler (role=client) cannot edit a field, add, or remove", () => {
    const { result } = renderStore({ role: "client" });
    act(() => {
      result.current.getState().editNodeField("n1", "title", "Hacked");
      result.current.getState().addNode({ type: "note", title: "Sneaky" });
      result.current.getState().removeNode("n1");
    });
    const { nodes } = result.current.getState();
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.title).toBe("Original");
  });

  test("staff with the lock but no credentials cannot mutate (no token → no-op)", () => {
    // Mirrors the prototype sandbox: advisor + startLocked but null creds.
    const { result } = renderStore({ role: "advisor", startLocked: true });
    expect(selectEditable(result.current.getState())).toBe(true);
    act(() => {
      result.current.getState().editNodeField("n1", "title", "Hacked");
      result.current.getState().addNode({ type: "note", title: "Sneaky" });
      result.current.getState().removeNode("n1");
    });
    const { nodes } = result.current.getState();
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.title).toBe("Original");
  });

  test("startLocked seeds locked-by-me; default leaves it unlocked", () => {
    const locked = renderStore({ role: "advisor", startLocked: true });
    expect(locked.result.current.getState().lockStatus).toBe("locked-by-me");
    const unlocked = renderStore({ role: "advisor" });
    expect(unlocked.result.current.getState().lockStatus).toBe("unlocked");
  });
});
