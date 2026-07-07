// Pure derivations behind the per-trip Dashboard (M006/PS3): the money roll-up
// (grouped by currency, drafts/void excluded, payments net owed) and the single
// "next best action" chosen from real trip state. No React — just the judgement.

import { describe, expect, test } from "vitest";

import type { InvoiceResponse } from "@ov-black/api-client";

import {
  type ChargeableNode,
  chargedByNode,
  coverageByNode,
  deriveNextAction,
  effectiveNodeCost,
  firstUnpaidIssued,
  formatTiming,
  invoiceOwed,
  isChargeable,
  isPayable,
  reconcileBilling,
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

function chargeLine(over: { id: string; node_id: string; amount?: string }) {
  return {
    id: over.id,
    invoice_id: "inv-1",
    node_id: over.node_id,
    kind: "charge" as const,
    description: "",
    amount: over.amount ?? "100.00",
    currency: "USD",
    created_at: "2024-01-01T00:00:00Z",
  };
}

function node(over: Partial<ChargeableNode> & { id: string }): ChargeableNode {
  return {
    status: "approved",
    cost_amount: "100.00",
    cost_currency: "USD",
    title: "A node",
    ...over,
  };
}

describe("isChargeable", () => {
  test("only approved nodes with a cost + currency qualify", () => {
    expect(isChargeable(node({ id: "a" }))).toBe(true);
    expect(isChargeable(node({ id: "b", status: "proposed" }))).toBe(false);
    expect(isChargeable(node({ id: "c", cost_amount: null }))).toBe(false);
    expect(isChargeable(node({ id: "d", cost_currency: "" }))).toBe(false);
  });
});

describe("coverageByNode", () => {
  test("maps charge lines to their invoices (with amount); skips void invoices", () => {
    const cov = coverageByNode([
      invoice({ id: "iv1", lines: [chargeLine({ id: "l1", node_id: "n1", amount: "300.00" })] }),
      invoice({ id: "iv2", status: "void", lines: [chargeLine({ id: "l2", node_id: "n2" })] }),
    ]);
    expect(cov.get("n1")).toEqual([
      { invoiceId: "iv1", label: "Deposit", status: "issued", amount: 300 },
    ]);
    // A node only charged on a void invoice is not covered.
    expect(cov.has("n2")).toBe(false);
  });

  test("a reversed charge line no longer covers its node", () => {
    const cov = coverageByNode([
      invoice({
        id: "iv1",
        lines: [
          chargeLine({ id: "l1", node_id: "n1" }),
          {
            id: "rev",
            invoice_id: "iv1",
            node_id: "n1",
            kind: "reversal" as const,
            description: "void",
            amount: "-100.00",
            currency: "USD",
            reverses_line_item_id: "l1",
            created_at: "2024-01-02T00:00:00Z",
          },
        ],
      }),
    ]);
    expect(cov.has("n1")).toBe(false);
  });
});

describe("reconcileBilling", () => {
  test("reconciles trip total against invoiced/paid/outstanding + uninvoiced remainder", () => {
    const nodes = [
      node({ id: "n1", cost_amount: "8000.00" }),
      node({ id: "n2", cost_amount: "9000.00" }),
      node({ id: "n3", cost_amount: "1200.00" }),
    ];
    const invoices = [
      invoice({
        id: "dep",
        status: "paid",
        total: "8000.00",
        lines: [chargeLine({ id: "l1", node_id: "n1", amount: "8000.00" })],
        payments: [payment("8000.00")],
      }),
    ];
    const { rows, billableNodes, supplemental } = reconcileBilling({
      totals: { USD: "18200.00" },
      invoices,
      nodes,
    });
    const usd = rows.find((r) => r.currency === "USD");
    expect(usd?.tripTotal).toBeCloseTo(18200);
    expect(usd?.invoiced).toBeCloseTo(8000);
    expect(usd?.paid).toBeCloseTo(8000);
    expect(usd?.outstanding).toBeCloseTo(0);
    expect(usd?.uninvoiced).toBeCloseTo(10200); // Σ remaining: n2 9000 + n3 1200
    expect(usd?.uninvoicedCount).toBe(2); // n2 + n3 still owe a balance
    // n1 is fully covered (paid deposit); n2/n3 still carry a balance.
    expect(billableNodes.map((n) => n.id).sort()).toEqual(["n2", "n3"]);
    expect(supplemental).toBe(true); // an issued/paid invoice exists + balances remain
  });

  test("a node split across a deposit + balance nets to fully covered", () => {
    const nodes = [node({ id: "n1", cost_amount: "1000.00" })];
    // 30% on a deposit invoice, 70% on a balance invoice — the SAME node twice.
    const invoices = [
      invoice({
        id: "dep",
        label: "Deposit",
        status: "issued",
        total: "300.00",
        lines: [chargeLine({ id: "d1", node_id: "n1", amount: "300.00" })],
      }),
      invoice({
        id: "bal",
        label: "Balance",
        status: "issued",
        total: "700.00",
        lines: [chargeLine({ id: "b1", node_id: "n1", amount: "700.00" })],
      }),
    ];
    const { billableNodes, rows } = reconcileBilling({
      totals: { USD: "1000.00" },
      invoices,
      nodes,
    });
    // Fully billed → no remaining balance, drops out of the billable set.
    expect(billableNodes).toHaveLength(0);
    expect(rows.find((r) => r.currency === "USD")?.uninvoiced).toBeCloseTo(0);
  });

  test("a partial deposit leaves the node billable for its remainder", () => {
    const nodes = [node({ id: "n1", cost_amount: "1000.00" })];
    const invoices = [
      invoice({
        id: "dep",
        status: "issued",
        total: "300.00",
        lines: [chargeLine({ id: "d1", node_id: "n1", amount: "300.00" })],
      }),
    ];
    const { billableNodes } = reconcileBilling({
      totals: { USD: "1000.00" },
      invoices,
      nodes,
    });
    expect(billableNodes).toHaveLength(1);
    expect(billableNodes[0]).toMatchObject({
      id: "n1",
      effective: 1000,
      charged: 300,
      remaining: 700,
    });
  });

  test("per_person cost is party-expanded when measuring remaining", () => {
    const nodes = [
      node({ id: "n1", cost_amount: "750.00", cost_kind: "per_person" }),
    ];
    // A 750pp guide for a party of 2 costs 1500; a 500 deposit leaves 1000.
    const invoices = [
      invoice({
        id: "dep",
        status: "issued",
        total: "500.00",
        lines: [chargeLine({ id: "d1", node_id: "n1", amount: "500.00" })],
      }),
    ];
    const { billableNodes } = reconcileBilling({
      totals: { USD: "1500.00" },
      invoices,
      nodes,
      partySize: 2,
    });
    expect(billableNodes[0]).toMatchObject({ effective: 1500, remaining: 1000 });
  });

  test("no supplemental prompt when nothing is issued yet", () => {
    const { supplemental } = reconcileBilling({
      totals: { USD: "500.00" },
      invoices: [invoice({ status: "draft", total: "0.00", lines: [] })],
      nodes: [node({ id: "n1" })],
    });
    expect(supplemental).toBe(false);
  });
});

describe("effectiveNodeCost / chargedByNode", () => {
  test("per_person expands by party size; total bills at face value", () => {
    expect(effectiveNodeCost(node({ id: "a", cost_amount: "750.00", cost_kind: "per_person" }), 3)).toBe(2250);
    expect(effectiveNodeCost(node({ id: "b", cost_amount: "750.00", cost_kind: "per_person" }), 0)).toBe(750); // floored at 1
    expect(effectiveNodeCost(node({ id: "c", cost_amount: "9000.00", cost_kind: "total" }), 4)).toBe(9000);
    expect(effectiveNodeCost(node({ id: "d", cost_amount: "9000.00" }), 4)).toBe(9000); // unset kind = face value
  });

  test("sums a node's charge lines across invoices, minus reversed/void", () => {
    const charged = chargedByNode([
      invoice({ id: "dep", lines: [chargeLine({ id: "d1", node_id: "n1", amount: "300.00" })] }),
      invoice({ id: "bal", lines: [chargeLine({ id: "b1", node_id: "n1", amount: "700.00" })] }),
      invoice({ id: "void", status: "void", lines: [chargeLine({ id: "v1", node_id: "n1", amount: "999.00" })] }),
    ]);
    expect(charged.get("n1")).toBeCloseTo(1000);
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
