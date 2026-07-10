// The Journal's phase-5 atmosphere & scale (traveler-journal design). Pins:
//   · day-rail indexing AGREES with the elision markers — both read the same
//     0-based scaffold indices out of `toJournal` (the coverage invariant);
//   · the day rail renders "Day N of M", one dot per day + a compressed tick
//     per elision, and click jumps to the day section;
//   · diff mode's diverged days are ONE derivation (`toJournalDiff`'s
//     `divergedDays`) feeding both the second thread and the rail's dots;
//   · elision polish — expand walks the open days; the skip affordance jumps
//     past the span;
//   · cinema mode — a store FLAG mutually exclusive with diff mode; the Play
//     entry hides while comparing; the chrome fades; Esc exits; wheel pauses;
//   · the reduced-motion branches of the pure motion helpers (crossfade →
//     instant swap, smooth jump → instant jump);
//   · the ambient layer reads `ambient_image` off the ACTIVE node and falls
//     back to the mood tint when there is none.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

const getForkDiffMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    getForkDiff: (...args: unknown[]) => getForkDiffMock(...args),
  };
});

import type {
  ForkDiffResponse,
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { AmbientLayer } from "@/app/_components/itinerary-graph/views/journal/AmbientLayer";
import { CinemaPlayButton } from "@/app/_components/itinerary-graph/views/journal/Cinema";
import {
  dayIndexByNode,
  dayRailItems,
  railIndexCoverage,
  tailBelow,
} from "@/app/_components/itinerary-graph/views/journal/dayRailModel";
import { JournalView } from "@/app/_components/itinerary-graph/views/journal/JournalView";
import {
  ambientFadeSeconds,
  elisionExpandSeconds,
  scrollBehaviorFor,
} from "@/app/_components/itinerary-graph/views/journal/motion";
import { toJournal } from "@/app/_components/itinerary-graph/views/journal/toJournal";
import { toJournalDiff } from "@/app/_components/itinerary-graph/views/journal/toJournalDiff";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const TZ = 9;

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
  const { metadata, ...rest } = overrides;
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: id,
    source: null,
    source_id: null,
    metadata: {
      ...(start ? { start_time: start, duration_minutes: 60 } : {}),
      ...(metadata ?? {}),
    },
    ...rest,
  } as NodeResponse;
}

/** A contiguous June-2024 day scaffold starting on the 20th. */
function days(count: number): Array<{ date: string; label: string }> {
  return Array.from({ length: count }, (_, i) => ({
    date: `2024-06-${String(20 + i).padStart(2, "0")}`,
    label: `Day ${i + 1}`,
  }));
}

function timeline(
  itinerary: ItineraryResponse,
  nodes: NodeResponse[],
  dayCount: number,
): ItineraryTimeline {
  return {
    id: itinerary.id,
    label: itinerary.title,
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: TZ,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-30T23:59:00+09:00",
    days: days(dayCount),
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
  itinerary = TRUNK,
  nodes = [] as NodeResponse[],
  dayCount = 2,
  withAmbient = false,
  withPlay = false,
} = {}) {
  const t = timeline(itinerary, nodes, dayCount);
  const full: ItineraryGraphInit = {
    timeline: t,
    itineraryId: itinerary.id,
    status: itinerary.display_status ?? "with_traveler",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
  };
  return render(
    <itineraryGraphStore.Provider initial={full}>
      <TimelineDataProvider value={{ timeline: t, baselineTitle: null }}>
        <StoreProbe />
        {withAmbient ? <AmbientLayer /> : null}
        {withPlay ? <CinemaPlayButton /> : null}
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

const scrollIntoViewMock = vi.fn();

beforeEach(() => {
  storeApi = null;
  vi.clearAllMocks();
  // jsdom has no scrollIntoView — the components guard on typeof, so give
  // them one and observe the jumps through it.
  Element.prototype.scrollIntoView =
    scrollIntoViewMock as unknown as typeof Element.prototype.scrollIntoView;
  getForkDiffMock.mockResolvedValue({ ok: false, detail: "nope" });
});

// ── The pure derivations ──────────────────────────────────────────────────────
describe("dayRail derivation — indexing agreement", () => {
  test("day dots + elision ticks cover the scaffold exactly once, in order", () => {
    // Cards on Day 1 and Day 10 → days 2..9 collapse into one elision.
    const journal = toJournal({
      nodes: [
        mkNode("a", "2024-06-20T09:00:00+09:00"),
        mkNode("b", "2024-06-29T09:00:00+09:00"),
      ],
      edges: [],
      days: days(10),
      timezoneOffsetHours: TZ,
    });
    const items = dayRailItems(journal);
    expect(items.map((i) => i.kind)).toEqual(["day", "elision", "day"]);
    // The agreement invariant: exactly 0..9, no gaps, no duplicates — the
    // rail and the elision markers can never disagree about day indexing.
    expect(railIndexCoverage(items)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    const elision = items[1];
    expect(elision?.kind).toBe("elision");
    if (elision?.kind === "elision") {
      expect(elision.startIndex).toBe(1);
      expect(elision.endIndex).toBe(8);
      expect(elision.dayCount).toBe(8);
    }
  });

  test("dayIndexByNode maps plain cards, alt members, and diff ghosts", () => {
    const nodes = [
      mkNode("solo", "2024-06-20T09:00:00+09:00"),
      mkNode("alt-1", "2024-06-21T10:00:00+09:00", {
        metadata: {
          start_time: "2024-06-21T10:00:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
      mkNode("alt-2", "2024-06-21T10:30:00+09:00", {
        metadata: {
          start_time: "2024-06-21T10:30:00+09:00",
          duration_minutes: 60,
          alt_group: "g1",
        },
      }),
    ];
    const diff: ForkDiffResponse = {
      fork_id: "it-fork",
      baseline_id: "it-1",
      added: [],
      removed: [
        {
          change_id: "c-rem",
          kind: "removed",
          baseline_node_id: "b-rem",
          before: {
            title: "Tea house",
            type: "meal",
            status: "pending",
            metadata: {
              start_time: "2024-06-21T15:00:00+09:00",
              duration_minutes: 45,
            },
          },
        },
      ],
      changed: [],
      moved: [],
    } as ForkDiffResponse;
    const view = toJournalDiff({
      nodes,
      edges: [],
      days: days(2),
      timezoneOffsetHours: TZ,
      diff,
    });
    const byNode = dayIndexByNode(view.journal);
    expect(byNode.get("solo")).toBe(0);
    expect(byNode.get("alt-1")).toBe(1);
    expect(byNode.get("alt-2")).toBe(1);
    expect(byNode.get("ghost:c-rem")).toBe(1);
    // The lifted diverged-day set: day 2 carries the ghost; day 1 agrees.
    expect(view.divergedDays.has("2024-06-21")).toBe(true);
    expect(view.divergedDays.has("2024-06-20")).toBe(false);
  });
});

describe("tailBelow — the more-below counting", () => {
  test("sums off-screen days (elisions by their run) and names the first", () => {
    const probes = [
      { top: 100, days: 1, date: "2024-06-20" }, // on screen
      { top: 900, days: 6, date: "2024-06-21" }, // elision, below
      { top: 1400, days: 1, date: "2024-06-27" }, // below
    ];
    expect(tailBelow(probes, 800)).toEqual({ days: 7, date: "2024-06-21" });
    expect(tailBelow(probes, 2000)).toEqual({ days: 0, date: null });
  });
});

describe("motion helpers — the reduced-motion branches", () => {
  test("crossfades become instant swaps; smooth jumps become instant", () => {
    expect(scrollBehaviorFor(false)).toBe("smooth");
    expect(scrollBehaviorFor(true)).toBe("auto");
    expect(ambientFadeSeconds(false)).toBeGreaterThan(0.29);
    expect(ambientFadeSeconds(false)).toBeLessThan(0.61);
    expect(ambientFadeSeconds(true)).toBe(0);
    expect(elisionExpandSeconds(false)).toBeGreaterThan(0);
    expect(elisionExpandSeconds(true)).toBe(0);
  });
});

// ── The day rail ──────────────────────────────────────────────────────────────
describe("day rail", () => {
  const NODES = [
    mkNode("n1", "2024-06-20T09:00:00+09:00"),
    mkNode("n2", "2024-06-21T09:00:00+09:00"),
  ];

  test("renders Day N of M with one dot per day (desktop + mobile shapes)", () => {
    renderJournal({ nodes: NODES, dayCount: 2 });
    expect(screen.getByTestId("journal-day-rail")).toBeInTheDocument();
    expect(screen.getByTestId("journal-day-rail-mobile")).toBeInTheDocument();
    // Two days × the two responsive shapes.
    expect(screen.getAllByTestId("journal-day-rail-dot")).toHaveLength(4);
    expect(screen.getByTestId("journal-day-rail-label")).toHaveTextContent(
      "Day 1",
    );
    expect(screen.getByTestId("journal-day-rail-label")).toHaveTextContent(
      "of 2",
    );
  });

  test("click jumps to the day section; the current day follows activation", () => {
    renderJournal({ nodes: NODES, dayCount: 2 });
    const dots = screen.getAllByTestId("journal-day-rail-dot");
    scrollIntoViewMock.mockClear(); // the strip auto-centers on mount
    fireEvent.click(dots[1]!); // desktop rail, Day 2
    expect(scrollIntoViewMock).toHaveBeenCalled();
    const jumped = scrollIntoViewMock.mock.contexts[0] as HTMLElement;
    expect(jumped.getAttribute("data-date")).toBe("2024-06-21");
    // Activating a Day-2 card moves the "Day N of M" readout.
    act(() => api().focusNode("n2", "click"));
    expect(screen.getByTestId("journal-day-rail-label")).toHaveTextContent(
      "Day 2",
    );
  });

  test("an elided run compresses to a tick; a day trip renders no rail", () => {
    renderJournal({
      nodes: [
        mkNode("a", "2024-06-20T09:00:00+09:00"),
        mkNode("b", "2024-06-29T09:00:00+09:00"),
      ],
      dayCount: 10,
    });
    // One tick per shape — never eight dots for the elided days.
    expect(screen.getAllByTestId("journal-day-rail-elision")).toHaveLength(2);
    expect(screen.getAllByTestId("journal-day-rail-dot")).toHaveLength(4);
  });

  test("hidden on a single-day journal", () => {
    renderJournal({ nodes: [mkNode("n1", "2024-06-20T09:00:00+09:00")], dayCount: 1 });
    expect(screen.queryByTestId("journal-day-rail")).not.toBeInTheDocument();
  });
});

// ── Elision polish ────────────────────────────────────────────────────────────
describe("elision marker", () => {
  const SPARSE = [
    mkNode("a", "2024-06-20T09:00:00+09:00"),
    mkNode("b", "2024-06-29T09:00:00+09:00"),
  ];

  test("expands to walk the open days", () => {
    renderJournal({ nodes: SPARSE, dayCount: 10 });
    expect(screen.queryByTestId("journal-elision-days")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("journal-elision-toggle"));
    expect(screen.getByTestId("journal-elision-days")).toBeInTheDocument();
    expect(screen.getByText("Day 2 — open")).toBeInTheDocument();
    expect(screen.getByText("Day 9 — open")).toBeInTheDocument();
  });

  test("the skip affordance names and jumps to the day after the span", () => {
    renderJournal({ nodes: SPARSE, dayCount: 10 });
    const skip = screen.getByTestId("journal-elision-skip");
    expect(skip).toHaveTextContent("skip to Day 10");
    scrollIntoViewMock.mockClear(); // the strip auto-centers on mount
    fireEvent.click(skip);
    expect(scrollIntoViewMock).toHaveBeenCalled();
    const jumped = scrollIntoViewMock.mock.contexts[0] as HTMLElement;
    expect(jumped.getAttribute("data-date")).toBe("2024-06-29");
  });

  test("carries the addressing attributes the rail and tail cue read", () => {
    renderJournal({ nodes: SPARSE, dayCount: 10 });
    const marker = screen.getByTestId("journal-elision");
    expect(marker).toHaveAttribute("data-start-date", "2024-06-21");
    expect(marker).toHaveAttribute("data-day-count", "8");
  });
});

// ── Cinema mode ───────────────────────────────────────────────────────────────
describe("cinema mode", () => {
  const NODES = [
    mkNode("n1", "2024-06-20T09:00:00+09:00"),
    mkNode("n2", "2024-06-20T14:00:00+09:00"),
  ];

  test("cinema and diff mode are mutually exclusive", async () => {
    renderJournal({ itinerary: FORK, nodes: NODES, dayCount: 1 });
    act(() => api().setCinemaMode(true));
    expect(api().cinemaMode).toBe(true);
    // Entering compare exits cinema…
    act(() => api().setDiffMode(true));
    expect(api().diffMode).toBe(true);
    expect(api().cinemaMode).toBe(false);
    // …and entering cinema exits compare.
    act(() => api().setCinemaMode(true));
    expect(api().cinemaMode).toBe(true);
    expect(api().diffMode).toBe(false);
    await waitFor(() => expect(getForkDiffMock).toHaveBeenCalled());
  });

  test("the Play entry hides while diff mode is on", async () => {
    renderJournal({ itinerary: FORK, nodes: NODES, dayCount: 1, withPlay: true });
    expect(screen.getByTestId("journal-cinema-play")).toBeInTheDocument();
    act(() => api().setDiffMode(true));
    await waitFor(() =>
      expect(
        screen.queryByTestId("journal-cinema-play"),
      ).not.toBeInTheDocument(),
    );
  });

  test("playing fades the chrome; wheel pauses; Esc exits", async () => {
    renderJournal({ nodes: NODES, dayCount: 1 });
    act(() => api().setCinemaMode(true));
    // The overlay is up and the rail is faded out of the way.
    expect(screen.getByTestId("journal-cinema-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("journal-rail").className).toContain(
      "opacity-0",
    );
    // Any wheel input pauses the driver — a quiet Resume appears.
    fireEvent.wheel(window);
    expect(
      await screen.findByTestId("journal-cinema-resume"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("journal-cinema-resume"));
    await waitFor(() =>
      expect(
        screen.queryByTestId("journal-cinema-resume"),
      ).not.toBeInTheDocument(),
    );
    // Esc exits the mode entirely; the chrome returns.
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(api().cinemaMode).toBe(false));
    expect(
      screen.queryByTestId("journal-cinema-overlay"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-rail").className).not.toContain(
      "opacity-0",
    );
  });
});

// ── The ambient layer ─────────────────────────────────────────────────────────
describe("ambient layer", () => {
  test("reads ambient_image off the active node; mood tint when absent", () => {
    const nodes = [
      mkNode("n1", "2024-06-20T09:00:00+09:00", {
        metadata: {
          start_time: "2024-06-20T09:00:00+09:00",
          duration_minutes: 60,
          ambient_image: "https://img.test/kyoto.jpg",
        },
      }),
      mkNode("n2", "2024-06-20T14:00:00+09:00"),
    ];
    renderJournal({ nodes, dayCount: 1, withAmbient: true });
    // Before any interaction: the resting mood tint, no image fetched.
    expect(
      document.querySelector('[data-testid="journal-ambient-active"][data-image]'),
    ).toBeNull();
    // Activation swaps the wash to the node's watermark image.
    act(() => api().focusNode("n1", "click"));
    expect(
      document.querySelector(
        '[data-testid="journal-ambient-active"][data-image="https://img.test/kyoto.jpg"]',
      ),
    ).not.toBeNull();
    // A node without an image falls back to the tint (a fresh tint pane
    // enters; the image pane is exiting).
    act(() => api().focusNode("n2", "click"));
    const panes = screen.getAllByTestId("journal-ambient-active");
    expect(panes.some((el) => !el.hasAttribute("data-image"))).toBe(true);
  });
});
