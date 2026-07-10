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

// The management panels each have their own tests; stub them so this asserts
// the Dashboard's own wiring (which panels appear for whom).
vi.mock("@/app/_components/itinerary-graph/views/horizontal/PartyPanel", () => ({
  PartyPanel: () => <div data-testid="stub-party-panel" />,
}));
vi.mock("@/app/_components/itinerary-graph/views/horizontal/VaultPanel", () => ({
  VaultPanel: () => <div data-testid="stub-vault-panel" />,
}));
vi.mock("@/app/_components/itinerary-graph/views/horizontal/InvoicePanel", () => ({
  InvoicePanel: () => <div data-testid="stub-invoice-panel" />,
}));
vi.mock("@/app/_components/itinerary-graph/views/horizontal/BookingPanel", () => ({
  BookingPanel: () => <div data-testid="stub-booking-panel" />,
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
        <ConciergeControlProvider value={{ openConcierge }}>
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

describe("DashboardView · money roll-up", () => {
  test("shows owed per currency, a pay link, and the per-inventory deep-link", async () => {
    listInvoicesMock.mockResolvedValue({
      ok: true,
      invoices: [
        invoice({
          id: "inv-1",
          status: "issued",
          total: "1000.00",
          payments: [{ id: "p1", status: "succeeded", amount: "400.00", currency: "USD", gateway: "s", gateway_reference: "r" }],
          lines: [
            { id: "l1", invoice_id: "inv-1", node_id: "n-1", kind: "charge", description: "Aman Tokyo", amount: "1000.00", currency: "USD", created_at: "x" },
          ],
        }),
      ],
    });
    renderDashboard();

    const money = await screen.findByTestId("dashboard-money");
    // Owed = 1000 − 400 settled.
    expect(money).toHaveTextContent("USD 600.00");
    expect(money).toHaveTextContent(/1 invoice issued/);

    // Pay from the roll-up → the existing /invoices/[id] page.
    expect(within(money).getByTestId("dashboard-invoice-pay")).toHaveAttribute(
      "href",
      "/invoices/inv-1",
    );
    // The charge line rolls down to that card's own money facet.
    expect(within(money).getByTestId("dashboard-invoice-line")).toHaveAttribute(
      "href",
      "/itinerary/it-1/item/n-1",
    );
  });

  test("an empty ledger reads as nothing to settle", async () => {
    renderDashboard({ role: "client" });
    await waitFor(() =>
      expect(screen.getByTestId("dashboard-money-empty")).toBeInTheDocument(),
    );
  });
});

describe("DashboardView · next best action", () => {
  test("a traveler with a balance is pointed to pay it", async () => {
    listInvoicesMock.mockResolvedValue({
      ok: true,
      invoices: [invoice({ id: "inv-7", status: "issued", total: "250.00" })],
    });
    renderDashboard({ role: "client" });
    await waitFor(() =>
      expect(screen.getByTestId("dashboard-next-cta")).toHaveAttribute("href", "/invoices/inv-7"),
    );
    expect(screen.getByTestId("dashboard-next-action")).toHaveTextContent(/settle your balance/i);
  });

  test("an empty-timeline traveler is nudged to the concierge", async () => {
    const openConcierge = vi.fn();
    renderDashboard({ role: "client" }, [], openConcierge);
    // The concierge action is a button, not a link.
    const cta = await screen.findByTestId("dashboard-next-cta");
    fireEvent.click(cta);
    expect(openConcierge).toHaveBeenCalledOnce();
  });
});

describe("DashboardView · role split", () => {
  test("an advisor sees the management panels", async () => {
    renderDashboard({ role: "advisor" });
    expect(screen.getByTestId("dashboard-manage")).toBeInTheDocument();
    // Party is its own section (the advisor attach/detach panel).
    expect(screen.getByTestId("stub-party-panel")).toBeInTheDocument();
    // Invoices tab is default-selected in the management strip.
    expect(screen.getByTestId("stub-invoice-panel")).toBeInTheDocument();
  });

  test("a traveler never sees the management panels, gets a read-only party glance", async () => {
    listItineraryPartyMock.mockResolvedValue({
      ok: true,
      party: { itinerary_id: "it-1", members: [{ traveler_id: "t1", party_id: "p1", name: "Ada" }] },
    });
    renderDashboard({ role: "client" });
    expect(screen.queryByTestId("dashboard-manage")).not.toBeInTheDocument();
    expect(screen.queryByTestId("stub-party-panel")).not.toBeInTheDocument();
    const party = screen.getByTestId("dashboard-party");
    await waitFor(() => expect(party).toHaveTextContent("Ada"));
  });
});
