// M005/I2 — traveler-facing pay view (Braintree Hosted Fields).
//
// The invoice wrappers + Braintree Hosted Fields are mocked so we assert the
// view's wiring:
//   - an issued invoice mounts Hosted Fields with a fetched client token,
//   - the breakdown + trip context render from the invoice + pay-context,
//   - the billing form is pre-filled from pay-context and forwarded to payInvoice,
//   - Pay → tokenize → payInvoice with the nonce → shows the receipt,
//   - a paid invoice shows the receipt and never mounts Hosted Fields,
//   - a settlement invoice locks a quote and pays with quote_id.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const { clientCreate, hostedFieldsCreate } = vi.hoisted(() => ({
  clientCreate: vi.fn(),
  hostedFieldsCreate: vi.fn(),
}));

vi.mock("braintree-web", () => ({
  default: {
    client: { create: clientCreate },
    hostedFields: { create: hostedFieldsCreate },
  },
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
  type InvoicePayContextResponse,
  type InvoiceResponse,
} from "@ov-black/api-client";

import { PayInvoiceView } from "@/app/invoices/[id]/_components/PayInvoiceView";

function invoice(over: Partial<InvoiceResponse> = {}): InvoiceResponse {
  return {
    id: "inv-1",
    number: 42,
    itinerary_id: "itin-1",
    label: "Deposit",
    status: "issued",
    currency: "USD",
    due_at: null,
    total: "750.00",
    subtotals: { USD: "750.00" },
    created_at: "2026-06-27T00:00:00Z",
    lines: [
      {
        id: "l1",
        invoice_id: "inv-1",
        node_id: "n1",
        kind: "charge",
        description: "Kaiseki dinner",
        amount: "750.00",
        currency: "USD",
        created_at: "2026-06-27T00:00:00Z",
      },
    ],
    payments: [],
    ...over,
  } as InvoiceResponse;
}

function payContext(
  over: Partial<InvoicePayContextResponse> = {},
): InvoicePayContextResponse {
  return {
    itinerary_title: "Kyoto in autumn",
    full_name: "Ada Lovelace",
    address: "1 Analytical Way",
    city: "London",
    region: "LDN",
    postal_code: "EC1A 1AA",
    country_code: "GB",
    preferred_currency: null,
    ...over,
  };
}

const tokenize = vi.fn();
const teardown = vi.fn(() => Promise.resolve());

const paidInvoice = () =>
  invoice({
    status: "paid",
    payments: [
      {
        id: "p1",
        status: "succeeded",
        amount: "750.00",
        currency: "USD",
        gateway: "braintree",
        gateway_reference: "ref-1",
        processor_transaction_id: "txn-1",
        instrument_type: "credit_card",
        last_four: "1111",
        created_at: "2026-06-27T00:00:00Z",
      },
    ],
  });

beforeEach(() => {
  vi.clearAllMocks();
  tokenize.mockResolvedValue({ nonce: "fake-valid-nonce" });
  clientCreate.mockResolvedValue({});
  hostedFieldsCreate.mockResolvedValue({ tokenize, teardown });
  vi.mocked(getInvoice).mockResolvedValue({ ok: true, invoice: invoice() });
  vi.mocked(getPaymentToken).mockResolvedValue({ ok: true, clientToken: "tok-123" });
  vi.mocked(payInvoice).mockResolvedValue({ ok: true, invoice: paidInvoice() });
});

function renderView(props: Partial<Parameters<typeof PayInvoiceView>[0]> = {}) {
  return render(
    <PayInvoiceView
      apiBaseUrl="http://api.test"
      accessToken="tok"
      invoiceId="inv-1"
      {...props}
    />,
  );
}

/** Wait until Hosted Fields mounted and the Pay button is enabled. */
async function waitForCardReady() {
  await waitFor(() => expect(hostedFieldsCreate).toHaveBeenCalled());
  await waitFor(() =>
    expect((screen.getByTestId("pay-submit") as HTMLButtonElement).disabled).toBe(false),
  );
}

test("issued invoice mounts Hosted Fields with a fetched client token", async () => {
  renderView();
  await screen.findByTestId("pay-submit");
  await waitFor(() => expect(getPaymentToken).toHaveBeenCalledWith({}, "inv-1"));
  await waitFor(() =>
    expect(clientCreate).toHaveBeenCalledWith(
      expect.objectContaining({ authorization: "tok-123" }),
    ),
  );
  await waitFor(() =>
    expect(hostedFieldsCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        fields: expect.objectContaining({
          number: expect.objectContaining({ selector: "#cc-number" }),
        }),
      }),
    ),
  );
  expect(screen.getByTestId("pay-submit").textContent).toContain("750.00");
});

test("renders the breakdown + trip context", async () => {
  renderView({ payContext: payContext() });
  await screen.findByTestId("pay-breakdown");
  expect(screen.getByTestId("pay-trip").textContent).toContain("Kyoto in autumn");
  expect(screen.getByTestId("pay-line").textContent).toContain("Kaiseki dinner");
  expect(screen.getByTestId("pay-total").textContent).toContain("750");
});

test("pre-fills billing from pay-context and forwards it to payInvoice", async () => {
  renderView({ payContext: payContext() });
  await waitForCardReady();
  // Pre-filled from the client record.
  expect((screen.getByTestId("billing-name") as HTMLInputElement).value).toBe("Ada Lovelace");
  expect((screen.getByTestId("billing-address") as HTMLInputElement).value).toBe(
    "1 Analytical Way",
  );
  expect((screen.getByTestId("billing-city") as HTMLInputElement).value).toBe("London");
  expect((screen.getByTestId("billing-country") as HTMLInputElement).value).toBe("GB");

  fireEvent.click(screen.getByTestId("pay-submit"));
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith(
      {},
      "inv-1",
      expect.objectContaining({
        payment_method_nonce: "fake-valid-nonce",
        billing_name: "Ada Lovelace",
        billing_address: "1 Analytical Way",
        billing_city: "London",
        billing_region: "LDN",
        billing_postal_code: "EC1A 1AA",
        billing_country: "GB",
      }),
    ),
  );
});

test("Pay tokenizes and posts the nonce, then shows the receipt", async () => {
  renderView();
  await waitForCardReady();
  fireEvent.click(screen.getByTestId("pay-submit"));
  await waitFor(() => expect(tokenize).toHaveBeenCalled());
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith(
      {},
      "inv-1",
      expect.objectContaining({ payment_method_nonce: "fake-valid-nonce" }),
    ),
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
  renderView({ demoTestCard: "4111111111111111" });
  const testCard = await screen.findByTestId("pay-test-card");
  // The configured sandbox card is shown, masked to last-4.
  expect(testCard.textContent).toContain("····1111");
  fireEvent.click(testCard);
  // Submits the sandbox nonce directly — never touches the Hosted Fields tokenizer.
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith(
      {},
      "inv-1",
      expect.objectContaining({ payment_method_nonce: "fake-valid-nonce" }),
    ),
  );
  expect(tokenize).not.toHaveBeenCalled();
  await screen.findByTestId("pay-receipt");
});

test("a paid invoice shows the receipt and never mounts Hosted Fields", async () => {
  vi.mocked(getInvoice).mockResolvedValue({ ok: true, invoice: paidInvoice() });
  renderView();
  await screen.findByTestId("pay-receipt");
  expect(screen.queryByTestId("pay-submit")).toBeNull();
  expect(clientCreate).not.toHaveBeenCalled();
  expect(hostedFieldsCreate).not.toHaveBeenCalled();
});

test("a settlement invoice locks a quote and pays with quote_id", async () => {
  vi.mocked(getInvoice).mockResolvedValue({
    ok: true,
    invoice: invoice({
      currency: "EUR",
      total: "1000.00",
      subtotals: { EUR: "1000.00" },
      settlement_currency: "USD",
      lines: [
        {
          id: "l1",
          invoice_id: "inv-1",
          node_id: "n1",
          kind: "charge",
          description: "Suite",
          amount: "1000.00",
          currency: "EUR",
          created_at: "2026-06-27T00:00:00Z",
        },
      ],
    } as Partial<InvoiceResponse>),
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

  await waitForCardReady();
  fireEvent.click(screen.getByTestId("pay-submit"));
  await waitFor(() =>
    expect(payInvoice).toHaveBeenCalledWith(
      {},
      "inv-1",
      expect.objectContaining({
        payment_method_nonce: "fake-valid-nonce",
        quote_id: "q1",
      }),
    ),
  );
});
