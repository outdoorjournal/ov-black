// M005/I2 — traveler-facing pay view (Braintree drop-in).
//
// The invoice wrappers + the Braintree drop-in are mocked so we assert the
// view's wiring:
//   - an issued invoice mounts the drop-in with a fetched client token,
//   - Pay → requestPaymentMethod → payInvoice with the nonce → shows the receipt,
//   - a paid invoice shows the receipt and never mounts the drop-in.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const { create } = vi.hoisted(() => ({ create: vi.fn() }));

vi.mock("braintree-web-drop-in", () => ({
  default: { create },
}));

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getInvoice: vi.fn(),
  getPaymentToken: vi.fn(),
  payInvoice: vi.fn(),
  createPaymentQuote: vi.fn(),
}));

import {
  createPaymentQuote,
  getInvoice,
  getPaymentToken,
  payInvoice,
  type InvoiceResponse,
} from "@ov-black/api-client";

import { PayInvoiceView } from "@/app/invoices/[id]/_components/PayInvoiceView";

function invoice(over: Partial<InvoiceResponse> = {}): InvoiceResponse {
  return {
    id: "inv-1",
    itinerary_id: "itin-1",
    label: "Deposit",
    status: "issued",
    currency: "USD",
    due_at: null,
    total: "750.00",
    created_at: "2026-06-27T00:00:00Z",
    lines: [],
    payments: [],
    ...over,
  } as InvoiceResponse;
}

const requestPaymentMethod = vi.fn();
const teardown = vi.fn(() => Promise.resolve());

beforeEach(() => {
  vi.clearAllMocks();
  requestPaymentMethod.mockResolvedValue({ nonce: "fake-valid-nonce" });
  create.mockResolvedValue({ requestPaymentMethod, teardown });
  vi.mocked(getInvoice).mockResolvedValue({ ok: true, invoice: invoice() });
  vi.mocked(getPaymentToken).mockResolvedValue({
    ok: true,
    clientToken: "tok-123",
  });
  vi.mocked(payInvoice).mockResolvedValue({
    ok: true,
    invoice: invoice({
      status: "paid",
      payments: [
        {
          id: "p1",
          status: "succeeded",
          amount: "750.00",
          currency: "USD",
          gateway: "fake",
          gateway_reference: "ref-1",
          processor_transaction_id: "fake-ref-1",
          instrument_type: "credit_card",
          last_four: "1111",
          created_at: "2026-06-27T00:00:00Z",
        },
      ],
    }),
  });
});

function renderView() {
  return render(
    <PayInvoiceView apiBaseUrl="http://api.test" accessToken="tok" invoiceId="inv-1" />,
  );
}

test("issued invoice mounts the drop-in with a fetched client token", async () => {
  renderView();
  await screen.findByTestId("pay-submit");
  await waitFor(() => expect(getPaymentToken).toHaveBeenCalledWith({}, "inv-1"));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ authorization: "tok-123" }),
    ),
  );
  expect(screen.getByTestId("pay-submit").textContent).toContain("750.00");
});

test("Pay tokenizes and posts the nonce, then shows the receipt", async () => {
  renderView();
  await waitFor(() => expect(create).toHaveBeenCalled());
  fireEvent.click(screen.getByTestId("pay-submit"));
  await waitFor(() => expect(requestPaymentMethod).toHaveBeenCalled());
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith({}, "inv-1", {
      payment_method_nonce: "fake-valid-nonce",
    }),
  );
  await screen.findByTestId("pay-receipt");
  expect(screen.getByText(/paid in full/)).toBeTruthy();
  expect(screen.getByText(/····1111/)).toBeTruthy();
});

test("test-card button is absent unless the demo flag is on", async () => {
  renderView();
  await screen.findByTestId("pay-submit");
  expect(screen.queryByTestId("pay-test-card")).toBeNull();
});

test("demo test-card pays with the sandbox nonce, no card entry", async () => {
  render(
    <PayInvoiceView
      apiBaseUrl="http://api.test"
      accessToken="tok"
      invoiceId="inv-1"
      demoTestCard="4111111111111111"
    />,
  );
  const testCard = await screen.findByTestId("pay-test-card");
  // The configured sandbox card is shown, masked to last-4.
  expect(testCard.textContent).toContain("····1111");
  fireEvent.click(testCard);
  // Submits the sandbox nonce directly — never touches the drop-in tokenizer.
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith({}, "inv-1", {
      payment_method_nonce: "fake-valid-nonce",
    }),
  );
  expect(requestPaymentMethod).not.toHaveBeenCalled();
  await screen.findByTestId("pay-receipt");
});

test("a paid invoice shows the receipt and never mounts the drop-in", async () => {
  vi.mocked(getInvoice).mockResolvedValue({
    ok: true,
    invoice: invoice({
      status: "paid",
      payments: [
        {
          id: "p1",
          status: "succeeded",
          amount: "750.00",
          currency: "USD",
          gateway: "fake",
          gateway_reference: "ref-1",
          processor_transaction_id: null,
          instrument_type: "credit_card",
          last_four: "4242",
          created_at: "2026-06-27T00:00:00Z",
        },
      ],
    }),
  });
  renderView();
  await screen.findByTestId("pay-receipt");
  expect(screen.queryByTestId("pay-submit")).toBeNull();
  expect(create).not.toHaveBeenCalled();
});

test("a settlement invoice locks a quote and pays with quote_id", async () => {
  vi.mocked(getInvoice).mockResolvedValue({
    ok: true,
    invoice: invoice({ currency: "EUR", total: "1000.00", settlement_currency: "USD" }),
  });
  vi.mocked(createPaymentQuote).mockResolvedValue({
    ok: true,
    quote: {
      id: "q1",
      invoiceId: "inv-1",
      settlementCurrency: "USD",
      settlementAmount: "1100.00",
      rates: { EUR: "1.10" },
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
    },
  });
  renderView();
  // The pay-currency lock is fetched and the headline shows it + a countdown.
  await waitFor(() => expect(createPaymentQuote).toHaveBeenCalledWith({}, "inv-1"));
  await waitFor(() =>
    expect(screen.getByTestId("pay-amount").textContent).toContain("$1,100"),
  );
  expect(screen.getByTestId("pay-settlement-note").textContent).toMatch(/rate locked/);

  fireEvent.click(await screen.findByTestId("pay-submit"));
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith({}, "inv-1", {
      payment_method_nonce: "fake-valid-nonce",
      quote_id: "q1",
    }),
  );
});
