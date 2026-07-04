// Pure derivations behind the per-trip Dashboard (M006/PS3): the money roll-up
// (grouped by currency, drafts/void excluded, payments net owed) and the single
// "next best action" chosen from real trip state. No React — just the judgement.

import { describe, expect, test } from "vitest";

import type { InvoiceResponse } from "@ov-black/api-client";

import {
  deriveNextAction,
  firstUnpaidIssued,
  formatTiming,
  invoiceOwed,
  isPayable,
  rollupInvoices,
} from "@/app/itinerary/[id]/_shell/dashboardModel";

function invoice(over: Partial<InvoiceResponse> = {}): InvoiceResponse {
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

function payment(amount: string, status: "succeeded" | "failed" | "refunded" = "succeeded") {
  return {
    id: `pay-${amount}-${status}`,
    status,
    amount,
    currency: "USD",
    gateway: "stripe",
    gateway_reference: "ref",
    created_at: "2024-01-01T00:00:00Z",
  };
}

describe("rollupInvoices", () => {
  test("nets settled payments against issued totals, per currency", () => {
    const { byCurrency, issuedCount, hasOwed } = rollupInvoices([
      invoice({ id: "a", status: "issued", total: "1000.00", payments: [payment("400.00")] }),
      invoice({ id: "b", status: "issued", currency: "EUR", total: "500.00" }),
    ]);
    expect(issuedCount).toBe(2);
    expect(hasOwed).toBe(true);
    const usd = byCurrency.find((c) => c.currency === "USD");
    const eur = byCurrency.find((c) => c.currency === "EUR");
    expect(usd?.owed).toBeCloseTo(600);
    expect(eur?.owed).toBeCloseTo(500);
    // Currencies stay grouped — never summed across.
    expect(byCurrency.map((c) => c.currency)).toEqual(["EUR", "USD"]);
  });

  test("excludes draft + void; paid contributes 0 owed", () => {
    const { byCurrency, issuedCount, hasOwed } = rollupInvoices([
      invoice({ id: "d", status: "draft", total: "9999.00" }),
      invoice({ id: "v", status: "void", total: "9999.00" }),
      invoice({ id: "p", status: "paid", total: "300.00", payments: [payment("300.00")] }),
    ]);
    expect(issuedCount).toBe(0);
    expect(hasOwed).toBe(false);
    // Only the paid invoice registers, fully settled.
    expect(byCurrency).toHaveLength(1);
    expect(byCurrency[0]?.owed).toBe(0);
    expect(byCurrency[0]?.paid).toBeCloseTo(300);
  });

  test("failed and refunded payments do not reduce owed", () => {
    expect(
      invoiceOwed(
        invoice({ total: "1000.00", payments: [payment("500.00", "failed"), payment("200.00", "refunded")] }),
      ),
    ).toBeCloseTo(1000);
  });
});

describe("firstUnpaidIssued / isPayable", () => {
  test("finds the first issued invoice still carrying a balance", () => {
    const settled = invoice({ id: "s", status: "issued", total: "100.00", payments: [payment("100.00")] });
    const owing = invoice({ id: "o", status: "issued", total: "250.00", payments: [payment("50.00")] });
    expect(isPayable(settled)).toBe(false);
    expect(isPayable(owing)).toBe(true);
    const first = firstUnpaidIssued([settled, owing]);
    expect(first).toEqual({ id: "o", currency: "USD", owed: 200 });
  });

  test("returns null when nothing is owed", () => {
    expect(firstUnpaidIssued([invoice({ status: "paid", payments: [payment("1000.00")] })])).toBeNull();
  });
});

describe("deriveNextAction", () => {
  const base = { scheduledCount: 3, pendingCount: 0, firstUnpaid: null, itineraryId: "it-1" };

  test("a traveler with a balance is pointed at paying it", () => {
    const a = deriveNextAction({
      ...base,
      role: "client",
      firstUnpaid: { id: "inv-9", currency: "USD", owed: 200 },
    });
    expect(a.target).toEqual({ kind: "href", href: "/invoices/inv-9" });
    expect(a.label).toMatch(/settle/i);
  });

  test("a traveler with an empty timeline is sent to the concierge", () => {
    const a = deriveNextAction({ ...base, role: "client", scheduledCount: 0 });
    expect(a.target).toEqual({ kind: "concierge" });
  });

  test("an advisor reviews proposals before anything else", () => {
    const a = deriveNextAction({
      ...base,
      role: "advisor",
      pendingCount: 2,
      firstUnpaid: { id: "inv-9", currency: "USD", owed: 200 },
    });
    expect(a.target).toEqual({ kind: "href", href: "/itinerary/it-1/timeline" });
    expect(a.detail).toMatch(/2 suggestions/);
  });

  test("an advisor with a settled, built trip lands on the timeline", () => {
    const a = deriveNextAction({ ...base, role: "advisor" });
    expect(a.target).toEqual({ kind: "href", href: "/itinerary/it-1/timeline" });
  });
});

describe("formatTiming", () => {
  test("exact dates render a range", () => {
    expect(
      formatTiming({ timing_kind: "exact", date_start: "2024-06-20", date_end: "2024-06-27" }),
    ).toMatch(/Jun 20, 2024.*Jun 27, 2024/);
  });

  test("window folds in the nights", () => {
    expect(
      formatTiming({ timing_kind: "window", date_start: "2024-06-01", date_end: "2024-06-30", duration_nights: 7 }),
    ).toMatch(/about 7 nights/);
  });

  test("flexible falls back to the note, then a default", () => {
    expect(formatTiming({ timing_kind: "flexible", timing_note: "not August" })).toBe("not August");
    expect(formatTiming({ timing_kind: "flexible" })).toBe("Dates flexible");
    expect(formatTiming({})).toBe("Dates to be decided");
  });
});
