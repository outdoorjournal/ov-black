// The per-item Finances table (doc/thoughts.md §3): a row per priced item with
// cost / invoiced / paid / remaining / deposit-due, and the deposit-paid badge
// inferred from paid ≥ deposit-due. Mocks the api-client fetches; the money math
// is exercised in dashboardModel.test.ts (deriveFinanceRows).

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const listInvoicesMock = vi.fn();
const getItineraryMock = vi.fn();
vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listInvoices: (...args: unknown[]) => listInvoicesMock(...args),
  getItinerary: (...args: unknown[]) => getItineraryMock(...args),
}));

import type { InvoiceResponse, NodeResponse } from "@ov-black/api-client";

import { FinancesTable } from "@/app/_components/itinerary-graph/views/horizontal/FinancesTable";

function node(over: Partial<NodeResponse> & { id: string }): NodeResponse {
  return {
    itinerary_id: "it-1",
    type: "hotel",
    status: "approved",
    title: "A node",
    cost_amount: "1000.00",
    cost_currency: "USD",
    cost_kind: "total",
    ...over,
  } as NodeResponse;
}

function chargeLine(id: string, nodeId: string, amount: string) {
  return {
    id,
    invoice_id: "inv",
    node_id: nodeId,
    kind: "charge" as const,
    description: "",
    amount,
    currency: "USD",
    created_at: "2024-01-01T00:00:00Z",
  };
}

function invoice(over: Partial<InvoiceResponse> & { id: string }): InvoiceResponse {
  return {
    itinerary_id: "it-1",
    label: "Deposit",
    status: "issued",
    currency: "USD",
    total: "0.00",
    created_at: "2024-01-01T00:00:00Z",
    lines: [],
    payments: [],
    ...over,
  } as InvoiceResponse;
}

beforeEach(() => {
  listInvoicesMock.mockReset();
  getItineraryMock.mockReset();
});

test("renders a row per priced item with the deposit due", async () => {
  getItineraryMock.mockResolvedValue({
    ok: true,
    nodes: [
      node({ id: "flight", type: "flight", title: "BA249", cost_amount: "1000.00" }),
      node({ id: "hotel", type: "hotel", title: "Aman", cost_amount: "2000.00" }),
    ],
    party_size: 1,
  });
  listInvoicesMock.mockResolvedValue({ ok: true, invoices: [] });

  render(<FinancesTable itineraryId="it-1" apiBaseUrl="http://x" accessToken="t" />);

  await waitFor(() => expect(screen.getByTestId("finances-table")).toBeTruthy());
  expect(screen.getByTestId("finance-row-flight")).toBeTruthy();
  expect(screen.getByTestId("finance-row-hotel")).toBeTruthy();
  // Deposit due: flight 100% ($1,000 — also its cost/remaining), hotel 20% ($400,
  // unique to the deposit column since the hotel costs $2,000).
  expect(screen.getAllByText("$1,000").length).toBeGreaterThan(0);
  expect(screen.getByText("$400")).toBeTruthy();
});

test("shows a deposit-paid badge once paid covers the deposit due", async () => {
  getItineraryMock.mockResolvedValue({
    ok: true,
    nodes: [node({ id: "n1", type: "hotel", title: "Ryokan", cost_amount: "1000.00" })],
    party_size: 1,
  });
  // A paid deposit invoice covering 20% ($200) → deposit captured.
  listInvoicesMock.mockResolvedValue({
    ok: true,
    invoices: [
      invoice({ id: "dep", status: "paid", lines: [chargeLine("d1", "n1", "200.00")] }),
    ],
  });

  render(<FinancesTable itineraryId="it-1" apiBaseUrl="http://x" accessToken="t" />);

  await waitFor(() => expect(screen.getByTestId("deposit-paid-n1")).toBeTruthy());
});
