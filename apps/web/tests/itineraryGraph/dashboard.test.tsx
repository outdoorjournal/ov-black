// The per-trip Dashboard (M006/PS3). These assert the view's COMPOSITION — the
// edit-in-place hero (phase 2 — its editor guts are covered in
// dashboardHero.test.tsx), the one derived next action, the money roll-up
// (owed · pay link · the per-inventory deep-link back down to the card), and
// the role split (advisor panels vs. a traveler's read-only party glance). The
// heavy leaves (the four management panels, next/link's router, the
// invoice/party reads) are stubbed so this tests the Dashboard, not their guts.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
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

// The travel-party panel (the advisor's attach/detach, opened from the hero
// party popover) has its own tests; stub it so this asserts the Dashboard's own
// wiring, not the panel's guts.
vi.mock("@/app/_components/itinerary-graph/views/horizontal/PartyPanel", () => ({
  PartyPanel: () => <div data-testid="stub-party-panel" />,
}));
const listInvoicesMock = vi.fn();
const listItineraryPartyMock = vi.fn();
const updateItineraryMock = vi.fn();
vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listInvoices: (...args: unknown[]) => listInvoicesMock(...args),
  listItineraryParty: (...args: unknown[]) => listItineraryPartyMock(...args),
  updateItinerary: (...args: unknown[]) => updateItineraryMock(...args),
}));

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { ConciergeControlProvider } from "@/app/itinerary/[id]/_shell/ConciergeControl";
import { DashboardView } from "@/app/itinerary/[id]/_shell/DashboardView";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Sailing in Greece",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
  brief: "Two weeks island-hopping with the family",
  timing_kind: "exact",
  date_start: "2024-06-20",
  date_end: "2024-07-04",
};

function scheduledNode(id: string): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "hotel",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: { start_time: "2024-06-20T15:00:00+03:00" },
  };
}

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Sailing in Greece",
    subtitle: "",
    mood: "tidal",
    timezoneOffsetHours: 3,
    windowStart: "2024-06-20T00:00:00+03:00",
    windowEnd: "2024-07-04T23:59:00+03:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

function invoice(over: Record<string, unknown> = {}) {
  return {
    id: "inv-1",
    itinerary_id: "it-1",
    label: "Deposit",
    status: "issued",
    currency: "USD",
    total: "1000.00",
    created_at: "2024-01-01T00:00:00Z",
    lines: [],
    payments: [],
    ...over,
  };
}

function renderDashboard(
  partial: Partial<ItineraryGraphInit> = {},
  nodes: NodeResponse[] = [scheduledNode("n-1")],
  openConcierge: () => void = () => {},
) {
  const init: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "in_studio",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  return render(
    <itineraryGraphStore.Provider initial={init}>
      <TimelineDataProvider value={{ timeline: timeline(nodes), baselineTitle: null }}>
        <ConciergeControlProvider value={{ openConcierge, nudge: 0 }}>
          <DashboardView />
        </ConciergeControlProvider>
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listInvoicesMock.mockResolvedValue({ ok: true, invoices: [] });
  listItineraryPartyMock.mockResolvedValue({ ok: true, party: { itinerary_id: "it-1", members: [] } });
  updateItineraryMock.mockResolvedValue({ ok: true, itinerary: ITINERARY });
});

describe("DashboardView · hero", () => {
  test("renders the brief, timing, and title as in-place editors — no overlay path", () => {
    renderDashboard();
    const hero = screen.getByTestId("dashboard-hero");
    expect(within(hero).getByRole("heading", { level: 1 })).toHaveTextContent("Sailing in Greece");
    expect(hero).toHaveTextContent("Two weeks island-hopping");
    expect(hero).toHaveTextContent(/Jun 20, 2024/);

    // Phase 2: the edit-overlay button is gone; each element edits in place
    // (the editors themselves are exercised in dashboardHero.test.tsx).
    expect(screen.queryByTestId("dashboard-hero-edit")).not.toBeInTheDocument();
    fireEvent.click(within(hero).getByTestId("hero-title"));
    expect(within(hero).getByTestId("hero-title-input")).toHaveValue("Sailing in Greece");
  });
});

describe("DashboardView · money callout", () => {
  test("the hero surfaces the balance due and deep-links to the pay page", async () => {
    listInvoicesMock.mockResolvedValue({
      ok: true,
      invoices: [
        invoice({
          id: "inv-1",
          status: "issued",
          total: "1000.00",
          payments: [{ id: "p1", status: "succeeded", amount: "400.00", currency: "USD", gateway: "s", gateway_reference: "r" }],
        }),
      ],
    });
    renderDashboard();

    const callout = await screen.findByTestId("hero-money");
    // Owed = 1000 − 400 settled.
    expect(callout).toHaveTextContent("USD 600.00");
    expect(callout).toHaveTextContent(/Balance due/i);
    // Pay from the callout → the existing /invoices/[id] page (first unpaid).
    expect(callout).toHaveAttribute("href", "/invoices/inv-1");
  });

  test("an empty ledger shows no money callout at all", async () => {
    renderDashboard({ role: "client" });
    // The hero renders immediately; the callout only appears once a non-empty
    // ledger loads, so give the fetch a tick and assert it stays absent.
    await screen.findByTestId("dashboard-hero");
    await waitFor(() =>
      expect(screen.queryByTestId("hero-money")).not.toBeInTheDocument(),
    );
  });
});

describe("DashboardView · travel party", () => {
  test("an advisor's party popover hosts the attach/detach panel", async () => {
    listItineraryPartyMock.mockResolvedValue({
      ok: true,
      party: { itinerary_id: "it-1", members: [{ traveler_id: "t1", party_id: "p1", name: "Ada" }] },
    });
    renderDashboard({ role: "advisor" });

    // The footer management strip is gone — Vault/Invoices/Booking are their own
    // Rail destinations now.
    expect(screen.queryByTestId("dashboard-manage")).not.toBeInTheDocument();

    const chip = await screen.findByTestId("hero-party");
    await waitFor(() => expect(chip).toHaveTextContent(/Travel party \(1\)/));
    // Closed by default; the advisor panel only mounts once the popover opens.
    expect(screen.queryByTestId("stub-party-panel")).not.toBeInTheDocument();
    fireEvent.click(chip);
    expect(screen.getByTestId("stub-party-panel")).toBeInTheDocument();
  });

  test("a traveler's party popover lists who's coming, no advisor panel", async () => {
    listItineraryPartyMock.mockResolvedValue({
      ok: true,
      party: { itinerary_id: "it-1", members: [{ traveler_id: "t1", party_id: "p1", name: "Ada" }] },
    });
    renderDashboard({ role: "client" });

    const chip = await screen.findByTestId("hero-party");
    fireEvent.click(chip);
    const popover = screen.getByTestId("hero-party-popover");
    expect(popover).toHaveTextContent("Ada");
    expect(within(popover).queryByTestId("stub-party-panel")).not.toBeInTheDocument();
  });

  // 0048: when the client has a preferred currency, the trip total leads with
  // the converted figure and keeps the native amount as a muted "from" line.
  test("trip total leads with the converted preferred-currency figure", () => {
    renderDashboard({
      status: "with_traveler",
      totals: { EUR: "2000.00" },
      displayCurrency: "USD",
      totalDisplay: "2200.00",
    });

    const display = screen.getByTestId("dashboard-trip-total-display");
    expect(display).toHaveAttribute("data-currency", "USD");
    expect(display).toHaveTextContent("USD 2200.00");
    // The native bucket stays visible as the secondary "from" line.
    const native = screen.getByTestId("dashboard-trip-total-row");
    expect(native).toHaveTextContent("from EUR 2000.00");
  });

  test("trip total shows native only when no preferred currency is set", () => {
    renderDashboard({
      status: "with_traveler",
      totals: { EUR: "2000.00" },
    });

    expect(screen.queryByTestId("dashboard-trip-total-display")).not.toBeInTheDocument();
    expect(screen.getByTestId("dashboard-trip-total-row")).toHaveTextContent("EUR 2000.00");
  });
});
