// The Journal's phase-4 diff mode (traveler-journal design). Pins:
//   · the compare entry — the version chip's toggle fetches `diff_fork` and
//     flips the same Journal DOM into compare (never a route);
//   · unified rendering on ONE spine — added stitch, changed dot, moved chip,
//     ghost rows for trunk-only nodes, the dashed second thread through
//     diverged days; the spine never splits for a version diff;
//   · gesture gating — drag, insert-on-the-line, and the rail's in-place
//     editors sit out while comparing (margin notes stay open);
//   · the rail — idle summarizes the divergence with the role-decided CTA
//     (traveler: request reconcile; advisor: one-pass reconcile), an active
//     diffed node shows the field-level before/after + accept / keep wired to
//     the per-`change_id` reconcile decisions, and `refused_booked` /
//     booked-baseline changes render as a lock explanation, not an error.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const pushMock = vi.fn();
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock, refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-fork/dashboard",
}));

const getForkDiffMock = vi.fn();
const reconcileForkMock = vi.fn();
const requestReconcileMock = vi.fn();
const cancelReconcileMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    getForkDiff: (...args: unknown[]) => getForkDiffMock(...args),
    reconcileFork: (...args: unknown[]) => reconcileForkMock(...args),
    requestReconcile: (...args: unknown[]) => requestReconcileMock(...args),
    cancelReconcile: (...args: unknown[]) => cancelReconcileMock(...args),
  };
});

import type {
  ForkDiffResponse,
  ItineraryResponse,
  NodeChangeResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { JournalVersionChip } from "@/app/_components/itinerary-graph/views/journal/JournalVersionChip";
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
  start: string | null,
  overrides: Partial<NodeResponse> = {},
): NodeResponse {
  return {
    id,
    itinerary_id: "it-fork",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: start ? { start_time: start, duration_minutes: 60 } : {},
    ...overrides,
  } as NodeResponse;
}

const NODES: NodeResponse[] = [
  mkNode("n-keep", "2024-06-20T08:00:00+09:00", { title: "Morning market" }),
  mkNode("n-add", "2024-06-20T11:00:00+09:00", { title: "Moss garden" }),
  mkNode("n-chg", "2024-06-20T13:00:00+09:00", { title: "Kaiseki lunch" }),
  mkNode("n-mov", "2024-06-20T16:00:00+09:00", { title: "River walk" }),
];

function ch(
  changeId: string,
  overrides: Partial<NodeChangeResponse> = {},
): NodeChangeResponse {
  return { change_id: changeId, kind: "changed", ...overrides };
}

const DIFF: ForkDiffResponse = {
  fork_id: "it-fork",
  baseline_id: "it-1",
  added: [ch("c-add", { kind: "added", fork_node_id: "n-add" })],
  removed: [
    ch("c-rem", {
      kind: "removed",
      baseline_node_id: "b-rem",
      before: {
        title: "Tea house",
        type: "meal",
        status: "pending",
        metadata: {
          start_time: "2024-06-20T09:30:00+09:00",
          duration_minutes: 45,
        },
      },
    }),
  ],
  changed: [
    ch("c-chg", {
      fork_node_id: "n-chg",
      baseline_node_id: "b-chg",
      fields: ["title"],
      before: { title: "Bento lunch", status: "pending", metadata: {} },
      after: { title: "Kaiseki lunch", status: "pending", metadata: {} },
    }),
  ],
  moved: [
    ch("c-mov", {
      kind: "moved",
      fork_node_id: "n-mov",
      baseline_node_id: "b-mov",
      fields: ["position"],
      before: { starts_at: "2024-06-20T10:00:00+09:00", status: "pending", metadata: {} },
      after: { starts_at: "2024-06-20T16:00:00+09:00", status: "pending", metadata: {} },
    }),
  ],
} as ForkDiffResponse;

function timeline(
  itinerary: ItineraryResponse,
  nodes: NodeResponse[],
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
    edges: [],
  };
}

type StoreApi = ReturnType<typeof itineraryGraphStore.useStoreApi>;
let storeApi: StoreApi | null = null;
function StoreProbe() {
  storeApi = itineraryGraphStore.useStoreApi();
  return null;
}

function api(): ReturnType<StoreApi["getState"]> {
  if (!storeApi) throw new Error("store not mounted");
  return storeApi.getState();
}

function renderJournal({
  itinerary = FORK,
  nodes = NODES,
  init = {} as Partial<ItineraryGraphInit>,
  withChip = false,
} = {}) {
  const t = timeline(itinerary, nodes);
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
        {withChip ? <JournalVersionChip /> : null}
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

async function enterDiffMode() {
  act(() => api().setDiffMode(true));
  await waitFor(() =>
    expect(screen.getByTestId("journal-diff-thread")).toBeInTheDocument(),
  );
}

beforeEach(() => {
  storeApi = null;
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/itinerary/it-fork/dashboard");
  getForkDiffMock.mockResolvedValue({ ok: true, diff: DIFF });
  reconcileForkMock.mockResolvedValue({
    ok: true,
    result: {
      itinerary: TRUNK,
      fork: FORK,
      outcomes: [
        { change_id: "c-add", kind: "added", result: "applied" },
        { change_id: "c-rem", kind: "removed", result: "applied" },
        { change_id: "c-chg", kind: "changed", result: "applied" },
        { change_id: "c-mov", kind: "moved", result: "applied" },
      ],
    },
  });
  requestReconcileMock.mockResolvedValue({ ok: true, itinerary: FORK });
  cancelReconcileMock.mockResolvedValue({ ok: true, itinerary: FORK });
});

// ── Entry: the version chip ───────────────────────────────────────────────────
describe("the version chip near the hero", () => {
  test("on a fork, Compare with the trip toggles diff mode and fetches the diff", async () => {
    renderJournal({ withChip: true });
    fireEvent.click(screen.getByTestId("journal-compare-toggle"));
    await waitFor(() =>
      expect(getForkDiffMock).toHaveBeenCalledWith(expect.anything(), "it-fork"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("journal-diff-thread")).toBeInTheDocument(),
    );
    // Exit restores the reading view.
    fireEvent.click(screen.getByTestId("journal-compare-toggle"));
    expect(screen.queryByTestId("journal-diff-thread")).not.toBeInTheDocument();
  });

  test("?compare=1 seeds diff mode (the reconcile-review deep link)", async () => {
    window.history.replaceState(null, "", "/itinerary/it-fork/dashboard?compare=1");
    renderJournal({ withChip: true, init: { role: "advisor" } });
    await waitFor(() =>
      expect(screen.getByTestId("journal-diff-thread")).toBeInTheDocument(),
    );
  });

  test("on the trunk with an open fork, the chip deep-links compare into the fork", () => {
    renderJournal({
      itinerary: TRUNK,
      withChip: true,
      init: { viewerOpenForkId: "it-fork", itineraryId: "it-1" },
    });
    expect(screen.getByTestId("journal-compare-link")).toHaveAttribute(
      "href",
      "/itinerary/it-fork/dashboard?compare=1",
    );
  });
});

// ── Unified rendering ─────────────────────────────────────────────────────────
describe("unified diff rendering (one spine)", () => {
  test("added stitch · changed dot · moved chip · ghost row, in trunk-time order", async () => {
    renderJournal();
    await enterDiffMode();

    // added — stitch + caption on the fork node.
    const added = screen.getByTestId("journal-diff-stitch");
    expect(added.closest("[data-node-id]")).toHaveAttribute(
      "data-node-id",
      "n-add",
    );
    expect(screen.getByTestId("journal-diff-added-caption")).toHaveTextContent(
      "new in this version",
    );

    // changed — the dot on the circle.
    expect(
      screen.getByTestId("journal-diff-dot").closest("[data-node-id]"),
    ).toHaveAttribute("data-node-id", "n-chg");

    // moved — the chip on the card.
    expect(
      screen.getByTestId("journal-diff-moved").closest("[data-node-id]"),
    ).toHaveAttribute("data-node-id", "n-mov");

    // removed — the ghost at its TRUNK time (09:30, after the 08:00 card).
    const ghost = screen.getByTestId("journal-ghost");
    expect(ghost).toHaveTextContent("Tea house");
    expect(ghost).toHaveTextContent("not in your version");
    const rows = Array.from(
      document.querySelectorAll("[data-node-id]"),
    ).map((el) => el.getAttribute("data-node-id"));
    expect(rows.indexOf("ghost:c-rem")).toBeGreaterThan(rows.indexOf("n-keep"));
    expect(rows.indexOf("ghost:c-rem")).toBeLessThan(rows.indexOf("n-add"));

    // Vocabulary guard: no spine split for a version diff.
    expect(screen.queryByTestId("journal-alt-group")).not.toBeInTheDocument();
  });

  test("the advisor reads the role-aware ghost caption", async () => {
    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();
    expect(screen.getByTestId("journal-ghost")).toHaveTextContent(
      "not in this version",
    );
  });
});

// ── Gesture gating ────────────────────────────────────────────────────────────
describe("diff mode disables the content gestures", () => {
  test("drag handles and the insert line sit out; margin notes stay", async () => {
    renderJournal(); // traveler on their own fork — normally fully editable
    expect(screen.getAllByTestId("journal-drag-handle").length).toBeGreaterThan(0);
    expect(screen.getByTestId("journal-add-plus")).toBeInTheDocument();

    await enterDiffMode();
    expect(screen.queryByTestId("journal-drag-handle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-add-plus")).not.toBeInTheDocument();
    // Notes are feedback, not a graph edit — the margin channel stays open.
    expect(screen.getAllByTestId("journal-margin-add").length).toBeGreaterThan(0);
  });

  test("the rail's in-place editor sits out while comparing", async () => {
    renderJournal();
    act(() => api().focusNode("n-chg", "click"));
    expect(screen.getByTestId("journal-rail-edit")).toBeInTheDocument();

    await enterDiffMode();
    act(() => api().focusNode("n-chg", "click"));
    expect(screen.queryByTestId("journal-rail-edit")).not.toBeInTheDocument();
    // …but the note action survives (reading/deciding mode, feedback stays).
    expect(screen.getByTestId("journal-rail-leave-note")).toBeInTheDocument();
  });
});

// ── The rail: divergence summary + decisions ──────────────────────────────────
describe("the rail in diff mode", () => {
  test("idle summarizes the divergence; the traveler's CTA is request reconcile", async () => {
    renderJournal();
    await enterDiffMode();
    expect(screen.getByTestId("journal-rail-diff-counts")).toHaveTextContent(
      "1 addition, 1 removal, 1 change, 1 move",
    );
    fireEvent.click(screen.getByTestId("journal-rail-request-reconcile"));
    await waitFor(() =>
      expect(requestReconcileMock).toHaveBeenCalledWith(
        expect.anything(),
        "it-fork",
      ),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("journal-rail-merge-requested"),
      ).toBeInTheDocument(),
    );
    // Role is the source of truth — no advisor reconcile button for a traveler.
    expect(screen.queryByTestId("journal-rail-reconcile")).not.toBeInTheDocument();
  });

  test("a changed node shows the field-level before/after; a traveler gets no decision buttons", async () => {
    renderJournal();
    await enterDiffMode();
    act(() => api().focusNode("n-chg", "click"));
    const field = screen.getByTestId("journal-rail-diff-field");
    expect(field).toHaveAttribute("data-field", "title");
    expect(field).toHaveTextContent("Bento lunch");
    expect(field).toHaveTextContent("Kaiseki lunch");
    expect(screen.queryByTestId("journal-rail-diff-accept")).not.toBeInTheDocument();
  });

  test("a moved node's rail shows old vs new time", async () => {
    renderJournal();
    await enterDiffMode();
    act(() => api().focusNode("n-mov", "click"));
    const times = screen.getByTestId("journal-rail-diff-times");
    expect(times).toHaveTextContent("Jun 20 · 10:00");
    expect(times).toHaveTextContent("Jun 20 · 16:00");
  });

  test("activating a ghost puts the removal in the rail", async () => {
    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();
    fireEvent.click(screen.getByRole("button", { name: /Tea house/ }));
    const change = screen.getByTestId("journal-rail-diff-change");
    expect(change).toHaveAttribute("data-kind", "removed");
    expect(screen.getByTestId("journal-rail-diff-accept")).toBeInTheDocument();
    // A synthesized ghost has no /item destination and takes no notes.
    expect(
      screen.queryByTestId("journal-rail-open-detail"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("journal-rail-leave-note"),
    ).not.toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  test("advisor: keep-the-original flows into the per-change reconcile decisions", async () => {
    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();

    // Keep the changed card as the original…
    act(() => api().focusNode("n-chg", "click"));
    fireEvent.click(screen.getByTestId("journal-rail-diff-keep"));
    expect(screen.getByTestId("journal-rail-diff-keep")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // …then reconcile from the idle summary: every change is decided in ONE
    // pass, the kept one as accept:false.
    act(() => api().focusNode(null));
    fireEvent.click(screen.getByTestId("journal-rail-reconcile"));
    await waitFor(() => expect(reconcileForkMock).toHaveBeenCalledTimes(1));
    expect(reconcileForkMock).toHaveBeenCalledWith(expect.anything(), "it-fork", {
      decisions: [
        { change_id: "c-add", accept: true },
        { change_id: "c-rem", accept: true },
        { change_id: "c-chg", accept: false },
        { change_id: "c-mov", accept: true },
      ],
    });
    // Fully resolved → back to the official trip.
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/itinerary/it-1"));
  });

  test("advisor: all-accept takes the server-side accept_all fast path", async () => {
    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();
    act(() => api().focusNode(null));
    fireEvent.click(screen.getByTestId("journal-rail-reconcile"));
    await waitFor(() =>
      expect(reconcileForkMock).toHaveBeenCalledWith(
        expect.anything(),
        "it-fork",
        { accept_all: true },
      ),
    );
  });

  test("fork_infeasible refuses the pass and points at the override flow", async () => {
    reconcileForkMock.mockResolvedValue({
      ok: false,
      status: 409,
      detail: "fork_infeasible",
    });
    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();
    fireEvent.click(screen.getByTestId("journal-rail-reconcile"));
    await waitFor(() =>
      expect(screen.getByTestId("journal-rail-diff-blocked")).toBeInTheDocument(),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  test("a booked baseline renders as a lock explanation, not buttons (refused_booked stays honest)", async () => {
    const bookedDiff: ForkDiffResponse = {
      ...DIFF,
      added: [],
      removed: [],
      moved: [],
      changed: [
        ch("c-chg", {
          fork_node_id: "n-chg",
          baseline_node_id: "b-chg",
          fields: ["title"],
          before: { title: "Bento lunch", status: "booked", metadata: {} },
          after: { title: "Kaiseki lunch", status: "booked", metadata: {} },
        }),
      ],
    } as ForkDiffResponse;
    getForkDiffMock.mockResolvedValue({ ok: true, diff: bookedDiff });

    renderJournal({ init: { role: "advisor" } });
    await enterDiffMode();
    act(() => api().focusNode("n-chg", "click"));
    expect(screen.getByTestId("journal-rail-diff-locked")).toBeInTheDocument();
    expect(
      screen.queryByTestId("journal-rail-diff-accept"),
    ).not.toBeInTheDocument();
  });
});
