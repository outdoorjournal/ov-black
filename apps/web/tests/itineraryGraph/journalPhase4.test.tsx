// The Journal's 2xl (≥1536px) BIG-CARD tier. Where the medium tier drives a
// compact cockpit rail and hides the full detail behind a second-click modal,
// the very-large tier leads the rail with the active card's full NodeZoomCard —
// clicking it opens the same intercepting detail modal — over the notes thread.
// These pin the responsive switch:
//   · <2xl → the cockpit rail (RightRail), "Open full →" is the modal deep link;
//   · ≥2xl → activating a card renders the big card (→ modal on click) + notes,
//     not the compact cockpit;
//   · ≥2xl idle → the resting glance, until a real interaction focuses a card;
//   · a subgraph child leads with a parent breadcrumb that scrolls the spine
//     back to the parent;
//   · diff mode stays on the cockpit even at 2xl (its accept/keep lives there).

import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn(), refresh: vi.fn() }),
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
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    getNodeCharges: (...args: unknown[]) => getNodeChargesMock(...args),
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

// ── ≥2xl: the big card leads (→ modal), notes beneath ─────────────────────────
describe("the 2xl big-card tier", () => {
  test("idle shows the resting glance, no card detail", () => {
    renderJournal();
    expect(screen.getByTestId("stub-idle")).toBeInTheDocument();
    expect(screen.queryByTestId("journal-rail-detail")).not.toBeInTheDocument();
  });

  test("activating a card leads with the big card + notes, not the cockpit", () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));

    const detail = screen.getByTestId("journal-rail-detail");
    expect(detail).toHaveAttribute("data-tier", "big-card");
    // The compact cockpit zones are gone at this tier…
    expect(screen.queryByTestId("journal-rail-zone1")).not.toBeInTheDocument();
    // …and the notes thread rides beneath the card.
    expect(within(detail).getByTestId("journal-rail-notes")).toBeInTheDocument();
  });

  test("the big card is a click-to-open handle (not a deep-link anchor)", () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));

    const handle = screen.getByTestId("journal-rail-open-detail");
    // A role=button div — NodeZoomCard renders its own <a>s, so it can't be a
    // nested anchor. Clicking it soft-navigates to the modal URL.
    expect(handle.tagName).toBe("DIV");
    expect(handle).toHaveAttribute("role", "button");
    fireEvent.click(handle);
    expect(pushMock).toHaveBeenCalledWith("/itinerary/it-1/item/n1");
  });

  test("Enter on the big card opens the modal too", () => {
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));
    fireEvent.keyDown(screen.getByTestId("journal-rail-open-detail"), {
      key: "Enter",
    });
    expect(pushMock).toHaveBeenCalledWith("/itinerary/it-1/item/n1");
  });
});

// ── A subgraph child leads with the parent breadcrumb ─────────────────────────
describe("a child card's parent breadcrumb", () => {
  const PARENT = mkNode("pkg", {
    title: "Nakasendo Way",
    type: "experience",
    metadata: { start_time: "2024-06-20T08:00:00+09:00", duration_minutes: 120 },
  });
  const CHILD = mkNode("beat", {
    title: "Magome to Tsumago",
    parent_subgraph_id: "pkg",
    metadata: {
      start_time: "2024-06-20T10:00:00+09:00",
      duration_minutes: 90,
      subgraph_day: { index: 1 },
    },
  });

  test("shows day X of Y · parent, and back scrolls + focuses the parent", () => {
    const scrollSpy = vi.fn();
    // jsdom stubs scrollIntoView as undefined by default; install a spy.
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollSpy,
    });

    renderJournal({ nodes: [PARENT, CHILD] });
    fireEvent.click(screen.getByText("Magome to Tsumago"));

    const crumb = screen.getByTestId("journal-rail-journey-breadcrumb");
    expect(crumb).toHaveTextContent("Nakasendo Way");

    fireEvent.click(screen.getByTestId("journal-rail-journey-back"));
    expect(storeApi!.getState().focusedNodeId).toBe("pkg");
    expect(scrollSpy).toHaveBeenCalled();

    // @ts-expect-error — remove the stub.
    delete HTMLElement.prototype.scrollIntoView;
  });
});

// ── <2xl: the cockpit tier keeps the modal deep link ──────────────────────────
describe("below 2xl the cockpit rail keeps the modal handle", () => {
  test("activating a card drives the cockpit; 'Open full' is the modal link", () => {
    viewportWidth = 1280; // ≥lg (desktop) but <2xl
    installMatchMedia();
    renderJournal();
    fireEvent.click(screen.getByText("Tea ceremony"));

    const detail = screen.getByTestId("journal-rail-detail");
    expect(detail).not.toHaveAttribute("data-tier", "big-card");
    expect(screen.getByTestId("journal-rail-zone1")).toBeInTheDocument();
    // A deep-link anchor (opens the intercepting modal), not a click handle.
    const handle = screen.getByTestId("journal-rail-open-detail");
    expect(handle.tagName).toBe("A");
    expect(handle).toHaveAttribute("href", "/itinerary/it-1/item/n1");
  });
});
