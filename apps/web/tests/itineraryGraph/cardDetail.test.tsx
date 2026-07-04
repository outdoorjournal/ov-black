// Card detail as a route (M006/PS4). The full-bleed detail view assembles six
// facets over a single node; here we assert the WIRING — that each facet renders
// from the shared store, that "ask about this" scopes the persistent concierge
// with a chip, and that the money facet reads the per-node charges endpoint.
// The heavy leaves (next/link's router, the money read, the session thread) are
// stubbed so these test the CardDetailView's own composition, not their guts.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useParams: () => ({ id: "it-1" }),
  usePathname: () => "/itinerary/it-1/timeline",
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

// The concierge's session thread fetches + streams; the chip integration test
// only needs the column shell around it, so stub the thread (it has its own test).
vi.mock("@/app/itinerary/[id]/_shell/SessionThread", () => ({
  SessionThread: ({ audience }: { audience: string }) => (
    <div data-testid={`thread-${audience}`} />
  ),
}));

const getNodeChargesMock = vi.fn();
vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getNodeCharges: (...args: unknown[]) => getNodeChargesMock(...args),
}));

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { CardDetailView } from "@/app/itinerary/[id]/_shell/CardDetailView";
import { ConciergeColumn } from "@/app/itinerary/[id]/_shell/ConciergeColumn";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

function node(id: string, over: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "hotel",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...over,
  };
}

const HOTEL = node("n-1", {
  title: "Aman Tokyo",
  cost_amount: "1000.00",
  cost_currency: "USD",
  metadata: {
    start_time: "2024-06-20T15:00:00+09:00",
    location: { lat: 35.6, lng: 139.7, label: "Otemachi" },
  },
});

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-21T23:59:00+09:00",
    days: [
      { date: "2024-06-20", label: "Day 1" },
      { date: "2024-06-21", label: "Day 2" },
    ],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

function charges(over: Record<string, unknown> = {}) {
  return {
    node_id: "n-1",
    node_status: "approved",
    currency: "USD",
    line_item_id: "li-1",
    invoice_id: "inv-1",
    invoice_status: "issued",
    billed_amount: "1000.00",
    paid_amount: "0.00",
    owed_amount: "1000.00",
    booking: null,
    ...over,
  };
}

function renderDetail(
  ui: ReactNode,
  nodes: NodeResponse[],
  partial: Partial<ItineraryGraphInit> = {},
) {
  const init: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "draft",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      <TimelineDataProvider value={{ timeline: timeline(nodes), baselineTitle: null }}>
        {children}
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
  return render(<>{ui}</>, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  getNodeChargesMock.mockResolvedValue({ ok: true, charges: charges() });
});

describe("CardDetailView · facets", () => {
  test("an editable advisor sees all six facets over the node", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { startLocked: true });

    // Header names the card.
    expect(screen.getByTestId("card-detail")).toHaveAttribute("data-node-id", "n-1");
    expect(
      screen.getByRole("heading", { level: 1, name: "Aman Tokyo" }),
    ).toBeInTheDocument();

    // (a) actions — a Maps link built from the node's location.
    const actions = screen.getByTestId("card-detail-actions");
    expect(within(actions).getByText("Open in Google Maps")).toHaveAttribute(
      "href",
      expect.stringContaining("35.6,139.7"),
    );
    // (c) notes, (d) ask, (e) scheduling (advisor holds the lock).
    expect(screen.getByTestId("notes-panel")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-ask")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-schedule")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-unschedule")).toBeInTheDocument();

    // (f) money — the per-node charges read fills in the ledger line.
    await waitFor(() => {
      const money = screen.getByTestId("card-detail-money");
      expect(money).toHaveTextContent("USD 1000.00");
    });
    expect(getNodeChargesMock).toHaveBeenCalledWith(expect.anything(), "it-1", "n-1");
  });

  test("a viewer without the lock gets no scheduling facet, still asks + sees money", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { role: "client" });
    expect(screen.queryByTestId("card-detail-schedule")).not.toBeInTheDocument();
    expect(screen.getByTestId("card-detail-ask")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("card-detail-money")).toHaveTextContent("USD 1000.00"),
    );
  });

  test("the money facet surfaces this item's booking status", async () => {
    getNodeChargesMock.mockResolvedValue({
      ok: true,
      charges: charges({
        node_status: "booked",
        paid_amount: "1000.00",
        owed_amount: "0.00",
        invoice_status: "paid",
        booking: { node_id: "n-1", node_status: "booked", supplier_ref: "ABC123" },
      }),
    });
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL]);
    await waitFor(() => {
      const booking = screen.getByTestId("card-detail-booking");
      expect(booking).toHaveTextContent("Booked");
      expect(booking).toHaveTextContent("ABC123");
    });
  });

  test("a missing node resolves to a graceful not-here state", () => {
    renderDetail(<CardDetailView nodeId="ghost" />, [HOTEL]);
    expect(screen.getByTestId("card-detail-missing")).toBeInTheDocument();
    expect(screen.queryByTestId("card-detail")).not.toBeInTheDocument();
  });
});

describe("CardDetailView · ask about this", () => {
  test("scopes the persistent concierge with a Re: chip, clearable", async () => {
    renderDetail(
      <>
        <ConciergeColumn onClose={() => {}} />
        <CardDetailView nodeId="n-1" />
      </>,
      [HOTEL],
      { startLocked: true },
    );

    // No chip until a card asks.
    expect(screen.queryByTestId("concierge-context-chip")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("card-detail-ask"));

    const chip = await screen.findByTestId("concierge-context-chip");
    expect(chip).toHaveTextContent("Aman Tokyo");

    // The ✕ clears the scope.
    fireEvent.click(screen.getByTestId("concierge-context-clear"));
    expect(screen.queryByTestId("concierge-context-chip")).not.toBeInTheDocument();
  });
});
