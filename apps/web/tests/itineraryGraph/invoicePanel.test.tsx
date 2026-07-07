// M005/I1 — advisor invoice panel (itinerary-aside Invoices tab).
//
// The invoice wrappers are mocked so we assert the panel's own wiring:
//   - on mount it renders each invoice's signed ledger + computed total,
//   - Create calls createInvoice with the label + currency,
//   - an adjustment posts a signed (negative) line via addInvoiceLineItem,
//   - Void on a line calls voidInvoiceLineItem,
//   - Issue calls issueInvoice,
//   - without the edit lock the assemble controls are hidden (read-only).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listInvoices: vi.fn(),
  getItinerary: vi.fn(),
  createInvoice: vi.fn(),
  addInvoiceLineItem: vi.fn(),
  voidInvoiceLineItem: vi.fn(),
  issueInvoice: vi.fn(),
  voidInvoice: vi.fn(),
}));

import {
  addInvoiceLineItem,
  createInvoice,
  getItinerary,
  issueInvoice,
  listInvoices,
  voidInvoiceLineItem,
  type InvoiceResponse,
  type NodeResponse,
} from "@ov-black/api-client";

import { InvoicePanel } from "@/app/_components/itinerary-graph/views/horizontal/InvoicePanel";

const INVOICE: InvoiceResponse = {
  id: "inv-1",
  itinerary_id: "itin-1",
  label: "Deposit",
  status: "draft",
  currency: "USD",
  due_at: null,
  total: "750.00",
  created_at: "2026-06-27T00:00:00Z",
  lines: [
    {
      id: "ln-charge",
      invoice_id: "inv-1",
      node_id: "node-1",
      kind: "charge",
      description: "Aman Kyoto",
      amount: "1000.00",
      currency: "USD",
      reverses_line_item_id: null,
      created_at: "2026-06-27T00:00:00Z",
    },
    {
      id: "ln-discount",
      invoice_id: "inv-1",
      node_id: null,
      kind: "discount",
      description: "Elderly discount",
      amount: "-250.00",
      currency: "USD",
      reverses_line_item_id: null,
      created_at: "2026-06-27T00:00:00Z",
    },
  ],
};

const NODE: NodeResponse = {
  id: "node-2",
  itinerary_id: "itin-1",
  parent_subgraph_id: null,
  type: "hotel",
  status: "approved",
  title: "Park Hyatt",
  source: null,
  source_id: null,
  metadata: {},
  cost_amount: "1200.00",
  cost_currency: "USD",
  cost_kind: "total",
  starts_at: null,
  duration_minutes: null,
  depth: 0,
  lock_reason: null,
  forked_from_node_id: null,
} as NodeResponse;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listInvoices).mockResolvedValue({ ok: true, invoices: [INVOICE] });
  vi.mocked(getItinerary).mockResolvedValue({
    ok: true,
    itinerary: {},
    nodes: [NODE],
    edges: [],
    totals: { USD: "1950.00" },
    party_size: 1,
  } as never);
  vi.mocked(createInvoice).mockResolvedValue({ ok: true, invoice: INVOICE });
  vi.mocked(addInvoiceLineItem).mockResolvedValue({
    ok: true,
    line: INVOICE.lines![1]!,
  });
  vi.mocked(voidInvoiceLineItem).mockResolvedValue({
    ok: true,
    line: INVOICE.lines![1]!,
  });
  vi.mocked(issueInvoice).mockResolvedValue({ ok: true, invoice: INVOICE });
});

function renderPanel(canManage = true) {
  return render(
    <InvoicePanel
      apiBaseUrl="http://api.test"
      accessToken="tok"
      itineraryId="itin-1"
      canManage={canManage}
    />,
  );
}

test("renders each invoice's signed ledger and total", async () => {
  renderPanel();
  await waitFor(() => expect(listInvoices).toHaveBeenCalledWith({}, "itin-1"));
  await screen.findByText("Deposit");
  expect(screen.getByTestId("invoice-total").textContent).toContain("750.00");
  expect(screen.getByText("Aman Kyoto")).toBeTruthy();
  expect(screen.getByText("Elderly discount")).toBeTruthy();
  expect(screen.getByText("-250.00 USD")).toBeTruthy();
});

test("Create posts the label + currency", async () => {
  renderPanel();
  await screen.findByTestId("invoice-create");
  fireEvent.click(screen.getByTestId("invoice-create"));
  await waitFor(() =>
    expect(createInvoice).toHaveBeenCalledWith({}, "itin-1", {
      label: "Deposit",
      currency: "USD",
    }),
  );
});

test("an adjustment posts a signed negative line", async () => {
  renderPanel();
  await screen.findByTestId("invoice-add-adjustment");
  fireEvent.change(screen.getByLabelText("Adjustment amount"), {
    target: { value: "-50.00" },
  });
  fireEvent.change(screen.getByLabelText("Adjustment description"), {
    target: { value: "Child" },
  });
  fireEvent.click(screen.getByTestId("invoice-add-adjustment"));
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      kind: "discount",
      description: "Child",
      amount: "-50.00",
      currency: "USD",
    }),
  );
});

test("charging a node with an explicit amount posts a partial charge line", async () => {
  renderPanel();
  await screen.findByTestId("invoice-charge-node");
  fireEvent.change(screen.getByTestId("invoice-charge-node"), {
    target: { value: "node-2" },
  });
  fireEvent.change(screen.getByLabelText("Charge amount"), {
    target: { value: "400" },
  });
  fireEvent.click(screen.getByTestId("invoice-charge-node-add"));
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
      amount: "400.00",
      currency: "USD",
      description: "Park Hyatt",
    }),
  );
});

test("charging a node with no amount bills its full remaining balance", async () => {
  renderPanel();
  await screen.findByTestId("invoice-charge-node");
  fireEvent.change(screen.getByTestId("invoice-charge-node"), {
    target: { value: "node-2" },
  });
  fireEvent.click(screen.getByTestId("invoice-charge-node-add"));
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
      amount: "1200.00",
      currency: "USD",
      description: "Park Hyatt",
    }),
  );
});

test("Void on a charge line voids it (append-only reversal)", async () => {
  renderPanel();
  await screen.findByTestId("line-void-ln-charge");
  fireEvent.click(screen.getByTestId("line-void-ln-charge"));
  await waitFor(() =>
    expect(voidInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", "ln-charge"),
  );
});

test("Issue issues the draft invoice", async () => {
  renderPanel();
  await screen.findByTestId("invoice-issue");
  fireEvent.click(screen.getByTestId("invoice-issue"));
  await waitFor(() => expect(issueInvoice).toHaveBeenCalledWith({}, "inv-1"));
});

test("read-only for a non-manager (traveler) — no assemble controls", async () => {
  renderPanel(false);
  await screen.findByText("Deposit");
  expect(screen.queryByTestId("invoice-create")).toBeNull();
  expect(screen.queryByTestId("invoice-issue")).toBeNull();
  expect(screen.queryByTestId("line-void-ln-charge")).toBeNull();
  expect(screen.getByText(/advisor manages invoicing/)).toBeTruthy();
});

test("reconciliation strip reconciles trip total vs invoiced + uninvoiced remainder", async () => {
  renderPanel();
  await screen.findByTestId("invoice-reconcile");
  const row = screen.getByTestId("invoice-reconcile-row");
  expect(row.getAttribute("data-currency")).toBe("USD");
  // Trip total comes from the graph `totals` (1,950). "Uninvoiced" is now the Σ of
  // node REMAINING balances: node-2 (1,200) is the only chargeable graph node and
  // it's unbilled, so 1,200 remains (amount-aware coverage, not tripTotal−invoiced).
  expect(screen.getByTestId("reconcile-trip-total").textContent).toContain("1,950");
  expect(screen.getByTestId("reconcile-uninvoiced").textContent).toContain("1,200");
});

test("Bill all remaining seeds a draft and charges each node's balance", async () => {
  renderPanel();
  const billAll = await screen.findByTestId("invoice-bill-all");
  // node-2 (1,200, unbilled) is the only node with a balance; node-1's draft charge
  // isn't a graph node here, so it doesn't count.
  expect(billAll.textContent).toContain("(1)");
  fireEvent.click(billAll);
  await waitFor(() =>
    expect(createInvoice).toHaveBeenCalledWith({}, "itin-1", {
      label: "Deposit",
      currency: "USD",
    }),
  );
  // Full remaining is posted as an explicit amount, tagged to the node.
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
      amount: "1200.00",
      currency: "USD",
      description: "Park Hyatt",
    }),
  );
});

test("a deposit % bills a fraction of each node's remaining now", async () => {
  renderPanel();
  await screen.findByTestId("invoice-bill-all");
  // Ask for a 25% deposit: node-2's 1,200 balance → a 300.00 charge line.
  fireEvent.change(screen.getByTestId("invoice-deposit-pct"), {
    target: { value: "25" },
  });
  fireEvent.click(screen.getByTestId("invoice-bill-all"));
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
      amount: "300.00",
      currency: "USD",
      description: "Park Hyatt",
    }),
  );
});

test("supplemental prompt appears once an invoice is issued and seeds the delta", async () => {
  // An issued invoice covering node-1, with node-2 still uncovered → supplemental.
  vi.mocked(listInvoices).mockResolvedValue({
    ok: true,
    invoices: [{ ...INVOICE, status: "issued" }],
  });
  renderPanel();
  const issue = await screen.findByTestId("invoice-supplemental-issue");
  expect(issue.getAttribute("data-currency")).toBe("USD");
  fireEvent.click(issue);
  await waitFor(() =>
    expect(createInvoice).toHaveBeenCalledWith({}, "itin-1", {
      label: "Supplemental",
      currency: "USD",
    }),
  );
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
      amount: "1200.00",
      currency: "USD",
      description: "Park Hyatt",
    }),
  );
});
