// B7 — advisor authoring: store actions (search / analyze / fill / accept) and
// the AuthoringPanel surface. The api-client wrappers are mocked so we assert
// the store wiring + UI without a live backend. The editable gate is exercised
// too: the two writes (add / accept) must no-op without the lock.

import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  acquireItineraryLock: vi.fn(async () => ({ ok: true })),
  releaseItineraryLock: vi.fn(async () => ({ ok: true })),
  approveItinerary: vi.fn(async () => ({ ok: true })),
  createNode: vi.fn(async () => ({ ok: true })),
  deleteNode: vi.fn(async () => ({ ok: true })),
  updateNode: vi.fn(async () => ({ ok: true })),
  searchInventory: vi.fn(),
  createNodeFromInventory: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysis: vi.fn(),
  fillGap: vi.fn(),
}));

import {
  createNodeFromInventory,
  fillGap,
  getAnalysis,
  searchInventory,
  startAnalysis,
  type AnalysisDetailResponse,
  type EdgeResponse,
  type FillProposalResponse,
  type FindingResponse,
  type ItineraryResponse,
  type MealItem,
  type NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { AuthoringPanel } from "@/app/_components/itinerary-graph/views/horizontal/AuthoringPanel";

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

const MEAL: MealItem = {
  source: "google_places",
  source_id: "p-saito",
  title: "Sushi Saito",
  kind: "meal",
  price: { amount_min: 300, amount_max: null, currency: "USD" },
};

const NEW_NODE: NodeResponse = {
  id: "n-new",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "meal",
  status: "proposed",
  title: "Sushi Saito",
  source: "google_places",
  source_id: "p-saito",
  metadata: {},
};

const FINDING: FindingResponse = {
  id: "f-1",
  node_id: "n1",
  severity: "warn",
  category: "location_flux",
  message: "Tokyo → Osaka in 30 min is not feasible by car.",
  evidence: { km: 400 },
  suggested_fix: null,
};

const PROPOSAL: FillProposalResponse = {
  inventory_source: "google_places",
  inventory_id: "p-saito",
  title: "Sushi Saito",
  type: "meal",
  starts_at: "2024-06-20T12:00:00+09:00",
  ends_at: "2024-06-20T13:30:00+09:00",
  location: { lat: 35.6, lng: 139.7 },
  score: 0.92,
  fits_in_gap: true,
  feasibility_unknown: false,
  drive_time_in_min: 12,
  drive_time_out_min: 12,
  party_ok: true,
  constraint_warnings: [],
  rationale: "A short hop from your morning, well inside the window.",
};

const ANALYSIS_DONE: AnalysisDetailResponse = {
  id: "an-1",
  itinerary_id: "it-1",
  status: "completed",
  depth: "standard",
  summary: "1 warning.",
  error_detail: null,
  started_at: null,
  completed_at: null,
  created_at: "2024-06-20T00:00:00Z",
  scope: {},
  result: {},
  external_calls: [],
  findings: [FINDING],
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

function initFor(partial: Partial<ItineraryGraphInit> = {}): ItineraryGraphInit {
  return {
    timeline: timeline([NODE]),
    itineraryId: "it-1",
    status: "draft",
    canEdit: true,
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    startLocked: true,
    ...partial,
  };
}

function renderStore(partial: Partial<ItineraryGraphInit> = {}) {
  const full = initFor(partial);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={full}>
      {children}
    </itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

// Let the store's fire-and-forget promise chains (.then/.finally) settle.
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(searchInventory).mockResolvedValue({
    ok: true,
    items: [MEAL],
    count: 1,
  });
  vi.mocked(createNodeFromInventory).mockResolvedValue({
    ok: true,
    node: NEW_NODE,
  });
  vi.mocked(startAnalysis).mockResolvedValue({
    ok: true,
    created: { analysis_id: "an-1", status: "queued" },
  });
  vi.mocked(getAnalysis).mockResolvedValue({ ok: true, analysis: ANALYSIS_DONE });
  vi.mocked(fillGap).mockResolvedValue({
    ok: true,
    result: { proposals: [PROPOSAL], analysis_id: null, analysis_age_seconds: null },
  });
});

describe("authoring store actions", () => {
  test("runInventorySearch populates results (advisor)", async () => {
    const { result } = renderStore();
    act(() => {
      result.current.getState().runInventorySearch({ keyword: "sushi" });
    });
    await flush();
    expect(searchInventory).toHaveBeenCalledWith(expect.anything(), {
      keyword: "sushi",
    });
    expect(result.current.getState().inventoryResults).toHaveLength(1);
    expect(result.current.getState().inventoryResults[0]!.title).toBe("Sushi Saito");
  });

  test("runInventorySearch is inert for a traveler (canEdit=false)", async () => {
    const { result } = renderStore({ canEdit: false, startLocked: false });
    act(() => {
      result.current.getState().runInventorySearch({ keyword: "sushi" });
    });
    await flush();
    expect(searchInventory).not.toHaveBeenCalled();
    expect(result.current.getState().inventoryResults).toHaveLength(0);
  });

  test("addNodeFromInventory appends a proposed node when editable", async () => {
    const { result } = renderStore();
    act(() => {
      result.current.getState().addNodeFromInventory("google_places", "p-saito");
    });
    await flush();
    expect(createNodeFromInventory).toHaveBeenCalledOnce();
    const { nodes } = result.current.getState();
    expect(nodes.map((n) => n.id)).toContain("n-new");
  });

  test("addNodeFromInventory is inert without the lock", async () => {
    const { result } = renderStore({ startLocked: false }); // canEdit but unlocked
    act(() => {
      result.current.getState().addNodeFromInventory("google_places", "p-saito");
    });
    await flush();
    expect(createNodeFromInventory).not.toHaveBeenCalled();
    expect(result.current.getState().nodes).toHaveLength(1);
  });

  test("startAnalyze then refreshAnalysis surfaces findings", async () => {
    const { result } = renderStore();
    act(() => {
      result.current.getState().startAnalyze();
    });
    await flush();
    expect(result.current.getState().analysisId).toBe("an-1");
    act(() => {
      result.current.getState().refreshAnalysis();
    });
    await flush();
    const s = result.current.getState();
    expect(s.analyzeStatus).toBe("completed");
    expect(s.findings).toHaveLength(1);
    expect(s.findings[0]!.severity).toBe("warn");
  });

  test("runFill sets ranked proposals", async () => {
    const { result } = renderStore();
    act(() => {
      result.current
        .getState()
        .runFill({ start: "2024-06-20T09:00:00+09:00", end: "2024-06-20T13:00:00+09:00" });
    });
    await flush();
    expect(fillGap).toHaveBeenCalledOnce();
    expect(result.current.getState().fillProposals).toHaveLength(1);
  });

  test("acceptFillProposal adds the node and drops the proposal", async () => {
    const { result } = renderStore();
    act(() => {
      result.current.getState().runFill({
        start: "2024-06-20T09:00:00+09:00",
        end: "2024-06-20T13:00:00+09:00",
      });
    });
    await flush();
    act(() => {
      result.current.getState().acceptFillProposal(PROPOSAL);
    });
    await flush();
    const s = result.current.getState();
    expect(s.nodes.map((n) => n.id)).toContain("n-new");
    expect(s.fillProposals).toHaveLength(0);
  });

  test("dismissFillProposal removes it without a write", async () => {
    const { result } = renderStore();
    act(() => {
      result.current.getState().runFill({
        start: "2024-06-20T09:00:00+09:00",
        end: "2024-06-20T13:00:00+09:00",
      });
    });
    await flush();
    act(() => {
      result.current.getState().dismissFillProposal("p-saito");
    });
    expect(result.current.getState().fillProposals).toHaveLength(0);
    expect(createNodeFromInventory).not.toHaveBeenCalled();
  });
});

describe("AuthoringPanel", () => {
  function renderPanel(partial: Partial<ItineraryGraphInit> = {}) {
    return render(
      <itineraryGraphStore.Provider initial={initFor(partial)}>
        <AuthoringPanel tzOffsetHours={9} days={[{ date: "2024-06-20" }]} />
      </itineraryGraphStore.Provider>,
    );
  }

  test("renders the search / analyze / fill sections", () => {
    renderPanel();
    expect(screen.getByTestId("itinerary-graph-search")).toBeDefined();
    expect(screen.getByTestId("itinerary-graph-analyze")).toBeDefined();
    expect(screen.getByTestId("itinerary-graph-fill")).toBeDefined();
  });

  test("search runs and renders a result with an enabled Add when locked", async () => {
    renderPanel();
    fireEvent.change(screen.getByTestId("itinerary-graph-search-input"), {
      target: { value: "sushi" },
    });
    fireEvent.click(screen.getByTestId("itinerary-graph-search-run"));
    await flush();
    expect(searchInventory).toHaveBeenCalledOnce();
    expect(screen.getByText("Sushi Saito")).toBeDefined();
    const add = screen.getByTestId("itinerary-graph-search-add") as HTMLButtonElement;
    expect(add.disabled).toBe(false);
  });

  test("without the lock, the panel warns and disables Add", async () => {
    renderPanel({ startLocked: false });
    expect(screen.getByTestId("itinerary-graph-authoring-locked")).toBeDefined();
    fireEvent.change(screen.getByTestId("itinerary-graph-search-input"), {
      target: { value: "sushi" },
    });
    fireEvent.click(screen.getByTestId("itinerary-graph-search-run"));
    await flush();
    const add = screen.getByTestId("itinerary-graph-search-add") as HTMLButtonElement;
    expect(add.disabled).toBe(true);
  });
});
