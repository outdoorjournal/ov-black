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

function renderPanel(editable = true) {
  return render(
    <InvoicePanel
      apiBaseUrl="http://api.test"
      accessToken="tok"
      itineraryId="itin-1"
      editable={editable}
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

test("read-only without the edit lock — no assemble controls", async () => {
  renderPanel(false);
  await screen.findByText("Deposit");
  expect(screen.queryByTestId("invoice-create")).toBeNull();
  expect(screen.queryByTestId("invoice-issue")).toBeNull();
  expect(screen.queryByTestId("line-void-ln-charge")).toBeNull();
  expect(screen.getByText(/Hold the edit lock/)).toBeTruthy();
});

test("reconciliation strip reconciles trip total vs invoiced + uninvoiced remainder", async () => {
  renderPanel();
  await screen.findByTestId("invoice-reconcile");
  const row = screen.getByTestId("invoice-reconcile-row");
  expect(row.getAttribute("data-currency")).toBe("USD");
  // Trip total from the graph `totals`; the draft doesn't count as invoiced, so the
  // whole 1,950 reads as uninvoiced. node-2 (1,200) is the one uncovered item.
  expect(screen.getByTestId("reconcile-trip-total").textContent).toContain("1,950");
  expect(screen.getByTestId("reconcile-uninvoiced").textContent).toContain("1,950");
});

test("Bill all uninvoiced seeds a draft and charges each uncovered node", async () => {
  renderPanel();
  const billAll = await screen.findByTestId("invoice-bill-all");
  // node-1 is already covered by the draft's charge line; node-2 is the only uninvoiced.
  expect(billAll.textContent).toContain("(1)");
  fireEvent.click(billAll);
  await waitFor(() =>
    expect(createInvoice).toHaveBeenCalledWith({}, "itin-1", {
      label: "Deposit",
      currency: "USD",
    }),
  );
  await waitFor(() =>
    expect(addInvoiceLineItem).toHaveBeenCalledWith({}, "inv-1", {
      node_id: "node-2",
      kind: "charge",
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
    }),
  );
});
