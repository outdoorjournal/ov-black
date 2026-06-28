// M005/I3 — advisor booking panel (itinerary-aside Booking tab).
//
// The booking wrappers are mocked so we assert the panel's own wiring:
//   - on mount it renders bookable nodes + the reconciliation banner,
//   - Book calls bookNode (override_unpaid false by default),
//   - the override checkbox books on a merely-issued line,
//   - Re-price on a flight calls refreshOffer and shows the held fare,
//   - Confirm posts the supplier ref via confirmNode,
//   - an unbalanced report renders the "Not reconciled" banner,
//   - without the edit lock the book/confirm controls are hidden (read-only).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getItinerary: vi.fn(),
  getReconciliation: vi.fn(),
  bookNode: vi.fn(),
  confirmNode: vi.fn(),
  refreshOffer: vi.fn(),
}));

import {
  bookNode,
  confirmNode,
  getItinerary,
  getReconciliation,
  refreshOffer,
  type NodeResponse,
  type OfferResponse,
  type ReconciliationResponse,
} from "@ov-black/api-client";

import { BookingPanel } from "@/app/_components/itinerary-graph/views/horizontal/BookingPanel";

function node(over: Partial<NodeResponse> & { id: string }): NodeResponse {
  return {
    itinerary_id: "itin-1",
    parent_subgraph_id: null,
    type: "hotel",
    status: "approved",
    title: "Item",
    source: null,
    source_id: null,
    metadata: {},
    cost_amount: "1000.00",
    cost_currency: "USD",
    cost_kind: "total",
    starts_at: null,
    duration_minutes: null,
    depth: 0,
    lock_reason: null,
    forked_from_node_id: null,
    ...over,
  } as NodeResponse;
}

const HOTEL = node({ id: "n-hotel", type: "hotel", title: "Park Hyatt", status: "approved" });
const FLIGHT = node({ id: "n-flight", type: "flight", title: "DL275", status: "approved" });
const BOOKED = node({ id: "n-booked", type: "hotel", title: "Aman", status: "booked" });

const BALANCED: ReconciliationResponse = {
  balanced: true,
  rows: [{ currency: "USD", paid_total: "1000.00", booked_total: "1000.00", balanced: true }],
  violations: [],
};

const OFFER: OfferResponse = {
  id: "off-1",
  node_id: "n-flight",
  source: "snapshot",
  source_offer_id: null,
  amount: "850.00",
  currency: "USD",
  priced_at: "2026-06-27T00:00:00Z",
  expires_at: "2026-06-27T00:30:00Z",
  refreshed_from_offer_id: null,
  created_at: "2026-06-27T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getItinerary).mockResolvedValue({
    ok: true,
    itinerary: {},
    nodes: [HOTEL, FLIGHT, BOOKED],
    edges: [],
  } as never);
  vi.mocked(getReconciliation).mockResolvedValue({ ok: true, reconciliation: BALANCED });
  vi.mocked(bookNode).mockResolvedValue({ ok: true, booking: {} } as never);
  vi.mocked(confirmNode).mockResolvedValue({ ok: true, booking: {} } as never);
  vi.mocked(refreshOffer).mockResolvedValue({ ok: true, offer: OFFER });
});

function renderPanel(editable = true) {
  return render(
    <BookingPanel
      apiBaseUrl="http://api.test"
      accessToken="tok"
      itineraryId="itin-1"
      editable={editable}
    />,
  );
}

test("renders bookable nodes and a balanced reconciliation banner", async () => {
  renderPanel();
  await waitFor(() => expect(getReconciliation).toHaveBeenCalledWith({}, "itin-1"));
  expect(screen.getByText("Park Hyatt")).toBeTruthy();
  expect(screen.getByText("DL275")).toBeTruthy();
  expect(screen.getByTestId("reconciliation-status").textContent).toContain("Reconciled");
});

test("Book posts the money gate (no override by default)", async () => {
  renderPanel();
  await screen.findByTestId("book-n-hotel");
  fireEvent.click(screen.getByTestId("book-n-hotel"));
  await waitFor(() =>
    expect(bookNode).toHaveBeenCalledWith({}, "itin-1", "n-hotel", {
      override_unpaid: false,
    }),
  );
});

test("the override checkbox books on a merely-issued line", async () => {
  renderPanel();
  await screen.findByTestId("override-n-hotel");
  fireEvent.click(screen.getByTestId("override-n-hotel"));
  fireEvent.click(screen.getByTestId("book-n-hotel"));
  await waitFor(() =>
    expect(bookNode).toHaveBeenCalledWith({}, "itin-1", "n-hotel", {
      override_unpaid: true,
    }),
  );
});

test("Re-price on a flight calls refreshOffer and shows the held fare", async () => {
  renderPanel();
  await screen.findByTestId("reprice-n-flight");
  fireEvent.click(screen.getByTestId("reprice-n-flight"));
  await waitFor(() =>
    expect(refreshOffer).toHaveBeenCalledWith({}, "itin-1", "n-flight"),
  );
  expect((await screen.findByTestId("offer-n-flight")).textContent).toContain("850.00");
});

test("Confirm posts the supplier ref on a booked node", async () => {
  renderPanel();
  await screen.findByTestId("confirm-ref-n-booked");
  fireEvent.change(screen.getByTestId("confirm-ref-n-booked"), {
    target: { value: "ABC123" },
  });
  fireEvent.click(screen.getByTestId("confirm-n-booked"));
  await waitFor(() =>
    expect(confirmNode).toHaveBeenCalledWith({}, "itin-1", "n-booked", {
      supplier_ref: "ABC123",
    }),
  );
});

test("an unbalanced report renders the Not reconciled banner", async () => {
  vi.mocked(getReconciliation).mockResolvedValue({
    ok: true,
    reconciliation: {
      balanced: false,
      rows: [{ currency: "USD", paid_total: "0.00", booked_total: "500.00", balanced: false }],
      violations: [
        {
          node_id: "n-booked",
          code: "booked_unpaid",
          currency: "USD",
          booked_amount: "500.00",
          paid_amount: "0.00",
        },
      ],
    },
  });
  renderPanel();
  expect((await screen.findByTestId("reconciliation-status")).textContent).toContain(
    "Not reconciled",
  );
});

test("read-only without the edit lock — no book/confirm controls", async () => {
  renderPanel(false);
  await screen.findByText("Park Hyatt");
  expect(screen.queryByTestId("book-n-hotel")).toBeNull();
  expect(screen.queryByTestId("confirm-n-booked")).toBeNull();
  expect(screen.getByText(/Hold the edit lock/)).toBeTruthy();
});
