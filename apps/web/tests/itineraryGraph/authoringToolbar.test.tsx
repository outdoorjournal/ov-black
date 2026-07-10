// M006 harmonization: the advisor authoring actions moved off the /studio route
// onto the Timeline. This covers the two seams that move added:
//   1. the unified Add composer's four modes (Details / Link / Find / Fill), with
//      Find/Fill rendering candidates through the common Card model; and
//   2. the Timeline toolbar — Add + Analyze for advisors on the routed timeline
//      (absent for travelers and when the standalone aside carries them instead).

import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  acquireItineraryLock: vi.fn(async () => ({ ok: true })),
  releaseItineraryLock: vi.fn(async () => ({ ok: true })),
  approveAllNodes: vi.fn(async () => ({ ok: true })),
  createNode: vi.fn(async () => ({ ok: true })),
  deleteNode: vi.fn(async () => ({ ok: true })),
  updateNode: vi.fn(async () => ({ ok: true })),
  searchInventory: vi.fn(),
  createNodeFromInventory: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysis: vi.fn(),
  fillGap: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/timeline",
}));

import {
  createNode,
  searchInventory,
  type ItineraryResponse,
  type MealItem,
  type NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { HorizontalView } from "@/app/_components/itinerary-graph/views/horizontal/HorizontalView";
import { CardComposer } from "@/app/itinerary/[id]/_shell/CardComposer";
import type { UserRole } from "@/lib/role";

// The advisor authoring surface is a WORKING COPY (a fork of the trunk) —
// trunk content only arrives via publish, so editable scenarios play out here.
const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
  forked_from_id: "trunk-0",
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

const MEAL: MealItem = {
  source: "google_places",
  source_id: "p-saito",
  title: "Sushi Saito",
  kind: "meal",
  price: { amount_min: 300, amount_max: null, currency: "USD" },
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

function initFor(partial: Partial<ItineraryGraphInit> = {}): ItineraryGraphInit {
  return {
    timeline: timeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    startLocked: true,
    ...partial,
  };
}

function withProviders(ui: ReactNode, partial: Partial<ItineraryGraphInit> = {}) {
  return (
    <itineraryGraphStore.Provider initial={initFor(partial)}>
      <TimelineDataProvider value={{ timeline: timeline(), baselineTitle: null }}>
        {ui}
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}

async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(searchInventory).mockResolvedValue({ ok: true, items: [MEAL], count: 1, sources: [] });
});

describe("unified Add composer — Details / Link / Find / Fill", () => {
  test("offers all four modes; Find and Fill fold the authoring sections in", async () => {
    render(withProviders(<CardComposer prefill={null} onClose={() => {}} />));

    for (const m of ["details", "link", "find", "fill"] as const) {
      expect(screen.getByTestId(`composer-mode-${m}`)).toBeDefined();
    }

    // Find → the inventory search section, and a result renders as a common Card.
    fireEvent.click(screen.getByTestId("composer-mode-find"));
    expect(screen.getByTestId("itinerary-graph-search")).toBeDefined();
    fireEvent.change(screen.getByTestId("itinerary-graph-search-input"), {
      target: { value: "sushi" },
    });
    fireEvent.click(screen.getByTestId("itinerary-graph-search-run"));
    await flush();
    expect(screen.getByTestId("itinerary-graph-search-result")).toBeDefined();
    expect(screen.getByText("Sushi Saito")).toBeDefined();

    // Fill → the gap section.
    fireEvent.click(screen.getByTestId("composer-mode-fill"));
    expect(screen.getByTestId("itinerary-graph-fill")).toBeDefined();
    expect(screen.getByTestId("itinerary-graph-fill-run")).toBeDefined();
  });

  test("placing at a slot offers all four modes with an editable scheduled time", () => {
    render(
      withProviders(
        <CardComposer prefill={{ dayKey: "2024-06-20", minute: 540 }} onClose={() => {}} />,
      ),
    );
    // Summoned from a timeline slot, the composer offers the same four modes as
    // the Collection path — no longer locked to Details.
    for (const m of ["details", "link", "find", "fill"] as const) {
      expect(screen.getByTestId(`composer-mode-${m}`)).toBeDefined();
    }
    // It opens on Details with the slot's time in an EDITABLE field (540 → 09:00).
    expect(screen.getByTestId("composer-title")).toBeDefined();
    const scheduleInput = screen.getByTestId("composer-schedule-input") as HTMLInputElement;
    expect(scheduleInput.value).toBe("2024-06-20T09:00");
    // Switching to Find drops the schedule field — Find lands in the Collection.
    fireEvent.click(screen.getByTestId("composer-mode-find"));
    expect(screen.getByTestId("itinerary-graph-search")).toBeDefined();
    expect(screen.queryByTestId("composer-schedule-input")).toBeNull();
  });

  test("editing the scheduled time persists the adjusted start", async () => {
    vi.mocked(createNode).mockResolvedValue({ ok: true } as never);
    render(
      withProviders(
        <CardComposer prefill={{ dayKey: "2024-06-20", minute: 540 }} onClose={() => {}} />,
      ),
    );
    fireEvent.change(screen.getByTestId("composer-title"), {
      target: { value: "Private tea ceremony" },
    });
    // Nudge the seeded 09:00 to 14:30 before adding.
    fireEvent.change(screen.getByTestId("composer-schedule-input"), {
      target: { value: "2024-06-20T14:30" },
    });
    fireEvent.click(screen.getByTestId("composer-submit"));
    await flush();
    // The persisted node carries the EDITED start (14:30 in the trip's +09:00).
    expect(createNode).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        body: expect.objectContaining({
          title: "Private tea ceremony",
          starts_at: "2024-06-20T14:30:00+09:00",
        }),
      }),
    );
  });
});

describe("Timeline toolbar — authoring lives here now", () => {
  // The routed timeline suppresses the in-canvas aside, so the toolbar IS the
  // authoring surface. (The prototype's aside path is exercised by the older
  // AuthoringPanel tests; rendering it here would drag in the whole chat/panels
  // stack.)
  function renderTimeline(role: UserRole) {
    return render(
      withProviders(
        <HorizontalView embedded showConciergeAside={false} onOpenNode={() => {}} />,
        { role },
      ),
    );
  }

  test("advisor sees Add + Analyze; Analyze opens the modal", () => {
    renderTimeline("advisor");
    expect(screen.getByTestId("itinerary-graph-add-card")).toBeDefined();
    // The legacy note quick-add is gone — Add is the unified composer now.
    expect(screen.queryByTestId("itinerary-graph-add-node")).toBeNull();
    const analyze = screen.getByTestId("itinerary-graph-tool-analyze");
    expect(screen.queryByTestId("analyze-modal")).toBeNull();
    fireEvent.click(analyze);
    expect(screen.getByTestId("analyze-modal")).toBeDefined();
    expect(screen.getByTestId("itinerary-graph-analyze")).toBeDefined();
  });

  test("a traveler sees no authoring toolbar", () => {
    renderTimeline("client");
    expect(screen.queryByTestId("itinerary-graph-add-card")).toBeNull();
    expect(screen.queryByTestId("itinerary-graph-tool-analyze")).toBeNull();
  });
});
