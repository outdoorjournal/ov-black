// The Journal's phase-4 tier: the 2xl (≥1536px) INLINE DETAIL. Where the
// medium tier drives a compact cockpit rail and hides the full detail behind a
// second click (the "Open full →" modal), the very-large tier promotes the
// right region to the full CardDetailView, permanent — selection IS the open.
// These pin the responsive switch:
//   · <2xl → the cockpit rail (RightRail), no inline detail;
//   · ≥2xl → activating a card renders the full detail inline, and the cockpit
//     (with its second-click "Open full →" handle) is gone;
//   · ≥2xl idle → the resting glance, until a real interaction focuses a card;
//   · diff mode stays on the cockpit even at 2xl (its accept/keep lives there).

import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useParams: () => ({ id: "it-1" }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string | { pathname?: string };
    children: ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : (href.pathname ?? "#")} {...rest}>
      {children}
    </a>
  ),
}));

const getNodeChargesMock = vi.fn();
const updateNodeMock = vi.fn();
const deleteNodeMock = vi.fn();
const updateNodeStatusMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    getNodeCharges: (...args: unknown[]) => getNodeChargesMock(...args),
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

// ── Viewport (matchMedia) harness ─────────────────────────────────────────────
// jsdom has no matchMedia; the components guard for that (→ small screen). Here
// we install a width-driven mock so we can pin behaviour on either side of 2xl.
let viewportWidth = 1920;
function installMatchMedia() {
  window.matchMedia = ((query: string) => {
    const m = query.match(/min-width:\s*(\d+)px/);
    const min = m ? Number.parseInt(m[1]!, 10) : 0;
    return {
      matches: viewportWidth >= min,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
      onchange: null,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
}

// ── Fixtures ──────────────────────────────────────────────────────────────────
const TRUNK: ItineraryResponse = {
  id: "it-1",
  title: "Kyoto in June",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "with_traveler",
};

function mkNode(id: string, overrides: Partial<NodeResponse> = {}): NodeResponse {
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

const FORK: ItineraryResponse = {
  ...TRUNK,
  id: "it-fork",
  forked_from_id: "it-1",
  display_status: "in_studio",
};

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

function renderJournal({
  itinerary = TRUNK,
  nodes = [HOST],
  init = {} as Partial<ItineraryGraphInit>,
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
        <JournalView railIdle={<div data-testid="stub-idle" />} />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

/** Focus a card, then press the cockpit's "Open full" to expand + lock. */
function expandCard(title: string) {
  fireEvent.click(screen.getByText(title));
  fireEvent.click(screen.getByTestId("journal-rail-open-detail"));
}

beforeEach(() => {
  storeApi = null;
  vi.clearAllMocks();
  viewportWidth = 1920;
  installMatchMedia();
  getNodeChargesMock.mockResolvedValue({
    ok: true,
    charges: {
      node_id: "n1",
      node_status: "pending",
      currency: null,
      line_item_id: null,
      invoice_id: null,
      invoice_status: null,
      billed_amount: "0.00",
      paid_amount: "0.00",
      owed_amount: "0.00",
      booking: null,
    },
  });
});

afterEach(() => {
  // @ts-expect-error — restore the jsdom default (absent) between tests.
  delete window.matchMedia;
});

// ── ≥2xl: cockpit leads, "Open full" expands + locks ──────────────────────────
describe("the 2xl inline-detail tier", () => {
  test("idle shows the resting glance, no cockpit detail, no inline detail", () => {
    renderJournal();
    expect(screen.getByTestId("stub-idle")).toBeInTheDocument();
    expect(screen.queryByTestId("journal-rail-detail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
  });

  test("activating a card leads with the cockpit, not the heavy inline detail", () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));

    // The cheap cockpit drives (follows the scroll-active card)…
    expect(screen.getByTestId("journal-rail-detail")).toBeInTheDocument();
    // …with an "Open full" EXPANDER (a button, not the modal deep link)…
    const handle = screen.getByTestId("journal-rail-open-detail");
    expect(handle.tagName).toBe("BUTTON");
    // …and the full detail is not mounted until asked for.
    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
    expect(storeApi!.getState().focusLocked).toBe(false);
  });

  test("'Open full' expands the detail BENEATH the cockpit and HARD-LOCKS focus", () => {
    renderJournal();
    expandCard("Tea ceremony");

    const inline = screen.getByTestId("journal-inline-detail");
    const detail = within(inline).getByTestId("card-detail");
    expect(detail).toHaveAttribute("data-node-id", "n1");
    expect(detail).toHaveAttribute("data-embedded", "true");
    // The cockpit STAYS on top (the detail expands underneath it)…
    expect(screen.getByTestId("journal-rail-detail")).toBeInTheDocument();
    // …the toggle flips to "Hide"…
    expect(screen.getByTestId("journal-rail-open-detail")).toHaveTextContent(
      "Hide full detail",
    );
    // …and focus is hard-locked so scrolling can't swap the card.
    expect(storeApi!.getState().focusLocked).toBe(true);
  });

  test("the expand toggle collapses again (and releases the lock)", () => {
    renderJournal();
    expandCard("Tea ceremony");
    // Press the same toggle (now "Hide full detail") to collapse.
    fireEvent.click(screen.getByTestId("journal-rail-open-detail"));
    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-rail-open-detail")).toHaveTextContent(
      "Open full detail",
    );
    expect(storeApi!.getState().focusLocked).toBe(false);
  });

  test("dismiss collapses back to the following cockpit and releases the lock", () => {
    renderJournal();
    expandCard("Tea ceremony");
    fireEvent.click(screen.getByTestId("card-detail-dismiss"));

    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-rail-detail")).toBeInTheDocument();
    expect(storeApi!.getState().focusLocked).toBe(false);
  });

  test("focusing another card drops the expansion + lock (back to its cockpit)", () => {
    const MOSS = mkNode("n2", {
      title: "Moss garden walk",
      metadata: { start_time: "2024-06-20T14:00:00+09:00", duration_minutes: 60 },
    });
    renderJournal({ nodes: [HOST, MOSS] });
    expandCard("Tea ceremony");
    expect(storeApi!.getState().focusLocked).toBe(true);

    fireEvent.click(screen.getByText("Moss garden walk"));
    // A deliberate move to another card wins: collapse + unlock, cockpit on n2.
    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("journal-rail-detail")).toBeInTheDocument();
    expect(storeApi!.getState().focusLocked).toBe(false);
    expect(storeApi!.getState().focusedNodeId).toBe("n2");
  });
});

// ── The expanded detail re-seeds its in-place editors per card ────────────────
describe("the expanded detail is keyed per node", () => {
  const MOSS = mkNode("n2", {
    title: "Moss garden walk",
    itinerary_id: "it-fork",
    metadata: { start_time: "2024-06-20T14:00:00+09:00", duration_minutes: 60 },
  });
  const TEA_FORK = mkNode("n1", {
    title: "Tea ceremony",
    itinerary_id: "it-fork",
    metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
  });

  test("the schedule facet's time follows the expanded card, not the first one", () => {
    // A fork so the editable ScheduleFacet renders (its time is seeded state —
    // the bug this pins is the panel instance persisting across a card change).
    renderJournal({ itinerary: FORK, nodes: [TEA_FORK, MOSS] });

    expandCard("Tea ceremony");
    expect(screen.getByTestId("card-detail-time")).toHaveValue("09:00");

    // Switch cards (collapses + unlocks), then expand the second one.
    expandCard("Moss garden walk");
    // Without the per-node key the input would still read 09:00 (stale state).
    expect(screen.getByTestId("card-detail-time")).toHaveValue("14:00");
    expect(screen.getByTestId("card-detail")).toHaveAttribute(
      "data-node-id",
      "n2",
    );
  });
});

// ── <2xl: the cockpit tier keeps the modal deep link ──────────────────────────
describe("below 2xl the cockpit rail keeps the modal handle", () => {
  test("activating a card drives the cockpit; 'Open full' is the modal link", () => {
    viewportWidth = 1280; // mdpi: ≥lg (desktop) but <2xl
    installMatchMedia();
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));

    expect(screen.getByTestId("journal-rail-detail")).toBeInTheDocument();
    // A deep-link anchor (opens the intercepting modal), not the expander.
    const handle = screen.getByTestId("journal-rail-open-detail");
    expect(handle.tagName).toBe("A");
    expect(handle).toHaveAttribute("href", "/itinerary/it-1/item/n1");
    expect(screen.queryByTestId("journal-inline-detail")).not.toBeInTheDocument();
  });
});
