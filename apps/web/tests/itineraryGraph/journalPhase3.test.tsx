// The Journal's phase-3 interaction depth (traveler-journal design). Pins the
// role-gated flows:
//   · insert on the line — the trunk offers ONLY Note; an editable fork grows
//     the Collection-first picker (place a wish-list item, blank card);
//   · approve from the rail — traveler per-node approval on the trunk;
//   · alternatives fork-in-the-spine — choose one (the existing approval
//     action), the unchosen collapse to the ghost chip, tap restores;
//   · problem states — caption + red-ring circle on the spine, explanation +
//     "get help" in the rail (driven by the typed metadata.problem socket);
//   · the editable rail detail — title / note / time edit in place on a fork,
//     and the trunk's legibility line instead of disabled buttons.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

const createNodeMock = vi.fn();
const updateNodeMock = vi.fn();
const deleteNodeMock = vi.fn();
const updateNodeStatusMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    createNode: (...args: unknown[]) => createNodeMock(...args),
    updateNode: (...args: unknown[]) => updateNodeMock(...args),
    deleteNode: (...args: unknown[]) => deleteNodeMock(...args),
    updateNodeStatus: (...args: unknown[]) => updateNodeStatusMock(...args),
  };
});

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const TRUNK: ItineraryResponse = {
  id: "it-1",
  title: "Kyoto in June",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "with_traveler",
};

const FORK: ItineraryResponse = {
  ...TRUNK,
  id: "it-fork",
  forked_from_id: "it-1",
  display_status: "in_studio",
};

function mkNode(
  id: string,
  overrides: Partial<NodeResponse> = {},
): NodeResponse {
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
    ...overrides,
  } as NodeResponse;
}

const HOST = mkNode("n1", {
  title: "Tea ceremony",
  metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
});

function timeline(
  itinerary: ItineraryResponse,
  nodes: NodeResponse[],
  edges: ItineraryTimeline["edges"] = [],
): ItineraryTimeline {
  return {
    id: itinerary.id,
    label: itinerary.title,
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary,
    nodes,
    edges,
  };
}

type StoreApi = ReturnType<typeof itineraryGraphStore.useStoreApi>;
let storeApi: StoreApi | null = null;
function StoreProbe() {
  storeApi = itineraryGraphStore.useStoreApi();
  return null;
}

function renderJournal({
  itinerary = TRUNK,
  nodes = [HOST],
  edges = [] as ItineraryTimeline["edges"],
  init = {} as Partial<ItineraryGraphInit>,
} = {}) {
  const t = timeline(itinerary, nodes, edges);
  const full: ItineraryGraphInit = {
    timeline: t,
    itineraryId: itinerary.id,
    status: itinerary.display_status ?? "with_traveler",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...init,
  };
  return render(
    <itineraryGraphStore.Provider initial={full}>
      <TimelineDataProvider value={{ timeline: t, baselineTitle: null }}>
        <StoreProbe />
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

let serverSeq = 0;

beforeEach(() => {
  storeApi = null;
  vi.clearAllMocks();
  createNodeMock.mockImplementation(
    (
      _c: unknown,
      { itineraryId, body }: { itineraryId: string; body: Record<string, unknown> },
    ) =>
      Promise.resolve({
        ok: true,
        node: {
          id: `srv-${++serverSeq}`,
          itinerary_id: itineraryId,
          parent_subgraph_id: null,
          type: body["type"],
          status: body["status"],
          title: body["title"],
          source: null,
          source_id: null,
          metadata:
            typeof body["starts_at"] === "string"
              ? { start_time: body["starts_at"] }
              : {},
        },
      }),
  );
  updateNodeMock.mockImplementation(
    (
      _c: unknown,
      { nodeId, patch }: { nodeId: string; patch: Record<string, unknown> },
    ) =>
      Promise.resolve({
        ok: true,
        node: { ...mkNode(nodeId), ...patch },
      }),
  );
  deleteNodeMock.mockResolvedValue({ ok: true });
  updateNodeStatusMock.mockResolvedValue({ ok: true });
});

// ── Insert on the line: trunk vs editable fork ────────────────────────────────
describe("the `+`-on-the-line picker (role-gated)", () => {
  test("on the trunk the line offers ONLY Note", () => {
    renderJournal();
    fireEvent.click(screen.getByTestId("journal-add-plus"));
    expect(screen.getByTestId("journal-add-note-option")).toBeInTheDocument();
    expect(
      screen.queryByTestId("journal-insert-collection"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("journal-insert-artemis"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-insert-blank")).not.toBeInTheDocument();
  });

  test("on the traveler's fork the picker leads with the Collection, then Artemis, Note, blank card", () => {
    const wish = mkNode("wish-1", {
      title: "Kaiseki dinner idea",
      type: "meal",
      itinerary_id: "it-fork",
    });
    renderJournal({ itinerary: FORK, nodes: [HOST, wish] });
    fireEvent.click(screen.getByTestId("journal-add-plus"));
    expect(screen.getByTestId("journal-insert-collection")).toHaveTextContent(
      "From your collection · 1",
    );
    expect(screen.getByTestId("journal-insert-artemis")).toBeInTheDocument();
    expect(screen.getByTestId("journal-add-note-option")).toBeInTheDocument();
    expect(screen.getByTestId("journal-insert-blank")).toBeInTheDocument();
  });

  test("placing a Collection item schedules it after the day's last card (start_synthesized-aware)", async () => {
    const wish = mkNode("wish-1", {
      title: "Kaiseki dinner idea",
      type: "meal",
      itinerary_id: "it-fork",
      // A synthesized start does NOT count as scheduled — still a wish.
      metadata: { start_time: "2024-06-20T08:00:00+09:00", start_synthesized: true },
    });
    renderJournal({ itinerary: FORK, nodes: [HOST, wish] });
    fireEvent.click(screen.getByTestId("journal-add-plus"));
    fireEvent.click(screen.getByTestId("journal-insert-collection"));
    fireEvent.click(screen.getByTestId("journal-insert-collection-item"));

    // Host runs 09:00–10:00 → the end-of-day slot is 10:30.
    await waitFor(() =>
      expect(updateNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-fork",
        nodeId: "wish-1",
        patch: {
          metadata: expect.objectContaining({
            start_time: expect.stringContaining("2024-06-20T10:30"),
          }),
        },
      }),
    );
    // The placed card sheds the synthesized marker.
    const call = updateNodeMock.mock.calls.find(
      (c) => (c[1] as { nodeId: string }).nodeId === "wish-1",
    );
    const patch = (call?.[1] as { patch: { metadata: Record<string, unknown> } })
      .patch;
    expect(patch.metadata["start_synthesized"]).toBeUndefined();
  });

  test("a blank card is authored scheduled into the same slot", async () => {
    renderJournal({ itinerary: FORK });
    fireEvent.click(screen.getByTestId("journal-add-plus"));
    fireEvent.click(screen.getByTestId("journal-insert-blank"));
    fireEvent.change(screen.getByTestId("journal-insert-blank-title"), {
      target: { value: "Moss garden walk" },
    });
    fireEvent.click(screen.getByTestId("journal-insert-blank-submit"));

    await waitFor(() =>
      expect(createNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-fork",
        body: expect.objectContaining({
          type: "experience",
          title: "Moss garden walk",
          status: "pending",
          starts_at: expect.stringContaining("2024-06-20T10:30"),
        }),
      }),
    );
  });
});

// ── Approve from the rail ─────────────────────────────────────────────────────
describe("approve from the rail (trunk, per node)", () => {
  test("activating a pending card offers Approve this; approving persists", async () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));
    const btn = screen.getByTestId("journal-rail-approve");
    fireEvent.click(btn);

    // Optimistic: the card firms up immediately…
    expect(storeApi!.getState().nodes.find((n) => n.id === "n1")?.status).toBe(
      "approved",
    );
    // …and the write goes through the existing per-node status endpoint.
    await waitFor(() =>
      expect(updateNodeStatusMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        nodeId: "n1",
        status: "approved",
      }),
    );
    // Approval locks the card — the approve action leaves the rail.
    expect(screen.queryByTestId("journal-rail-approve")).not.toBeInTheDocument();
  });

  test("no approve on a fork (approval lives on the trunk)", () => {
    renderJournal({ itinerary: FORK });
    fireEvent.click(screen.getByText("Tea ceremony"));
    expect(screen.queryByTestId("journal-rail-approve")).not.toBeInTheDocument();
  });
});

// ── Alternatives: fork in the spine ───────────────────────────────────────────
const ALT_A = mkNode("alt-a", {
  title: "Kaiseki at Kikunoi",
  type: "meal",
  metadata: { start_time: "2024-06-20T13:00:00+09:00", duration_minutes: 90 },
});
const ALT_B = mkNode("alt-b", {
  title: "Tempura counter",
  type: "meal",
  metadata: { start_time: "2024-06-20T13:15:00+09:00", duration_minutes: 90 },
});
const ALT_EDGE = {
  id: "e1",
  itinerary_id: "it-1",
  from_node_id: "alt-b",
  to_node_id: "alt-a",
  type: "alternative_to" as const,
  metadata: {},
};

describe("alternatives split the spine", () => {
  test("the group renders as parallel branches with a choose action per member", () => {
    renderJournal({ nodes: [HOST, ALT_A, ALT_B], edges: [ALT_EDGE] });
    const group = screen.getByTestId("journal-alt-group");
    expect(within(group).getAllByTestId("journal-alt-branch")).toHaveLength(2);
    expect(within(group).getAllByTestId("journal-alt-choose")).toHaveLength(2);
  });

  test("choosing one approves it; the unchosen collapses to the ghost chip; tap restores", async () => {
    renderJournal({ nodes: [HOST, ALT_A, ALT_B], edges: [ALT_EDGE] });
    const chooseA = screen
      .getAllByTestId("journal-alt-choose")
      .find((el) => el.getAttribute("data-node-id") === "alt-a")!;
    fireEvent.click(chooseA);

    // Choosing IS the existing approval action.
    await waitFor(() =>
      expect(updateNodeStatusMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-1",
        nodeId: "alt-a",
        status: "approved",
      }),
    );

    // The group collapses: the chosen stays a card, the unchosen is a ghost.
    const group = screen.getByTestId("journal-alt-group");
    expect(group).toHaveAttribute("data-collapsed", "true");
    const ghost = within(group).getByTestId("journal-alt-ghost");
    expect(ghost).toHaveTextContent("you also considered Tempura counter");
    expect(
      within(group)
        .getAllByTestId("journal-node")
        .map((el) => el.getAttribute("data-node-id")),
    ).not.toContain("alt-b");

    // Tap to restore: the split view returns (the unchosen is a real pending
    // node in the graph — the chip only collapsed it out of the story).
    fireEvent.click(ghost);
    expect(
      screen
        .getAllByTestId("journal-node")
        .map((el) => el.getAttribute("data-node-id")),
    ).toContain("alt-b");
    // No second choose offer once one is chosen; the collapse affordance shows.
    expect(screen.queryByTestId("journal-alt-choose")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("journal-alt-collapse"));
    expect(screen.getByTestId("journal-alt-ghost")).toBeInTheDocument();
  });
});

// ── Problem states ────────────────────────────────────────────────────────────
describe("problem states", () => {
  const troubled = mkNode("n-problem", {
    title: "Ryokan check-in",
    type: "hotel",
    metadata: {
      start_time: "2024-06-20T15:00:00+09:00",
      duration_minutes: 60,
      problem: { message: "Check-in overlaps the transfer from Kyoto Station." },
    },
  });

  test("the card wears the red-ring circle, the ⚠ glyph and a one-line caption", () => {
    renderJournal({ nodes: [HOST, troubled] });
    const row = screen
      .getAllByTestId("journal-node")
      .find((el) => el.getAttribute("data-node-id") === "n-problem")!;
    expect(
      within(row).getByTestId("journal-spine-circle"),
    ).toHaveAttribute("data-problem", "true");
    expect(within(row).getByTestId("journal-problem-glyph")).toBeInTheDocument();
    expect(within(row).getByTestId("journal-problem-caption")).toHaveTextContent(
      "Check-in overlaps the transfer",
    );
  });

  test("activating puts the explanation + get-help (chat pre-seeded) in the rail", () => {
    renderJournal({ nodes: [HOST, troubled] });
    fireEvent.click(screen.getByText("Ryokan check-in"));
    const rail = screen.getByTestId("journal-rail-problem");
    expect(rail).toHaveTextContent("Check-in overlaps the transfer");
    fireEvent.click(screen.getByTestId("journal-rail-get-help"));
    // The chat is pre-seeded with the node (the existing ask-context path).
    expect(storeApi!.getState().askContext).toEqual({
      nodeId: "n-problem",
      title: "Ryokan check-in",
    });
  });

  test("a healthy card carries no problem treatment", () => {
    renderJournal();
    expect(screen.queryByTestId("journal-problem-caption")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-problem-glyph")).not.toBeInTheDocument();
  });
});

// ── The editable rail detail (fork) + legibility (trunk) ──────────────────────
describe("editable rail detail", () => {
  test("on the traveler's fork: title edits in place, saves on blur", async () => {
    renderJournal({ itinerary: FORK });
    fireEvent.click(screen.getByText("Tea ceremony"));
    const panel = screen.getByTestId("journal-rail-edit");
    fireEvent.click(within(panel).getByTestId("journal-rail-edit-title"));
    const input = within(panel).getByTestId("journal-rail-edit-title-input");
    fireEvent.change(input, { target: { value: "Tea ceremony at dawn" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(updateNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-fork",
        nodeId: "n1",
        patch: { title: "Tea ceremony at dawn" },
      }),
    );
  });

  test("Escape cancels a title edit without a network call", () => {
    renderJournal({ itinerary: FORK });
    fireEvent.click(screen.getByText("Tea ceremony"));
    const panel = screen.getByTestId("journal-rail-edit");
    fireEvent.click(within(panel).getByTestId("journal-rail-edit-title"));
    const input = within(panel).getByTestId("journal-rail-edit-title-input");
    fireEvent.change(input, { target: { value: "never mind" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(updateNodeMock).not.toHaveBeenCalled();
  });

  test("the time slot edits in place and re-slots the card within its day", async () => {
    renderJournal({ itinerary: FORK });
    fireEvent.click(screen.getByText("Tea ceremony"));
    const panel = screen.getByTestId("journal-rail-edit");
    fireEvent.click(within(panel).getByTestId("journal-rail-edit-time"));
    const input = within(panel).getByTestId("journal-rail-edit-time-input");
    fireEvent.change(input, { target: { value: "14:00" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(updateNodeMock).toHaveBeenCalledWith(expect.anything(), {
        itineraryId: "it-fork",
        nodeId: "n1",
        patch: {
          metadata: expect.objectContaining({
            start_time: expect.stringContaining("2024-06-20T14:00"),
          }),
        },
      }),
    );
  });

  test("on the trunk there is no edit panel — the rail says where edits live instead", () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));
    expect(screen.queryByTestId("journal-rail-edit")).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-rail-readonly")).toHaveTextContent(
      "official trip",
    );
  });
});

// ── A flight's schedule is pinned to its booking (read-only + nudge) ───────────
describe("pinned flight — time is the airline's, not the traveler's", () => {
  const FLIGHT = mkNode("flt", {
    type: "flight",
    title: "Flight to Santiago",
    metadata: {
      start_time: "2024-06-20T16:10:00+09:00",
      duration_minutes: 700,
      depart_at: "2024-06-20T16:10:00+09:00",
      arrive_at: "2024-06-21T03:50:00+09:00",
    },
  });

  test("on the fork it offers a pinned nudge, not a drag handle", () => {
    renderJournal({ itinerary: FORK, nodes: [FLIGHT] });
    // No drag handle — the flight can't be re-timed by dragging.
    expect(screen.queryByTestId("journal-drag-handle")).not.toBeInTheDocument();
    // The nudge explains why, and reveals the concierge route on tap.
    const nudge = screen.getByTestId("journal-flight-pinned");
    expect(nudge).toHaveTextContent("Pinned to your flight booking");
    fireEvent.click(within(nudge).getByText("Pinned to your flight booking"));
    expect(within(nudge).getByText("Ask your concierge")).toBeInTheDocument();
  });

  test("the rail shows the time read-only (no editable input)", () => {
    renderJournal({ itinerary: FORK, nodes: [FLIGHT] });
    fireEvent.click(screen.getByText("Flight to Santiago"));
    expect(screen.getByTestId("journal-rail-time-pinned")).toHaveTextContent(
      "Set by the airline",
    );
    // The editable time affordance is absent for a pinned flight.
    expect(screen.queryByTestId("journal-rail-edit-time")).not.toBeInTheDocument();
  });

  test("moveNode is a no-op on a pinned flight (no re-time, no network write)", () => {
    renderJournal({ itinerary: FORK, nodes: [FLIGHT] });
    storeApi!.getState().moveNode("flt", "2024-06-21", 720);
    const moved = storeApi!
      .getState()
      .nodes.find((n) => n.id === "flt");
    expect((moved!.metadata as { start_time?: string }).start_time).toBe(
      "2024-06-20T16:10:00+09:00",
    );
    expect(updateNodeMock).not.toHaveBeenCalled();
  });
});
