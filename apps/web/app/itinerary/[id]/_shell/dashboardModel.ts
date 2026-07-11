// Pure derivations for the per-trip Dashboard (M006/PS3). Kept free of React so
// the view's judgement calls — chiefly "what's owed on this trip" — are
// unit-testable in isolation.

import type { InvoiceResponse, ItineraryPartyEntry } from "@ov-black/api-client";

// Async load states shared by the Dashboard shell and its hero — the hero now
// owns the money callout (right) and the travel-party chip (left), but the reads
// stay lifted in DashboardView so there's a single fetch per surface.
export type MoneyState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; invoices: InvoiceResponse[] };

export type PartyState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; members: ItineraryPartyEntry[] };

// ── Money roll-up ────────────────────────────────────────────────────────────
// The Dashboard is the trip-level LEDGER GLANCE (design §6): total owed, how many
// invoices are out, what's settled. The itemized per-inventory charge lives on the
// card (PS4) and rolls UP into these totals; a "what to pay" row deep-links back
// down to that card. Only ISSUED/PAID invoices count toward the glance — a `draft`
// is advisor-in-progress (assembled in the Invoices management panel, not yet owed)
// and `void` is dropped everywhere. Owed can't be summed across currencies, so the
// roll-up stays grouped by currency.

export type CurrencyRollup = {
  currency: string;
  /** Σ over issued invoices of (total − settled payments), floored at 0. */
  owed: number;
  /** Σ settled payments across issued + paid invoices. */
  paid: number;
  /** Σ totals across issued + paid invoices. */
  billed: number;
};

const settledPaid = (inv: InvoiceResponse): number =>
  (inv.payments ?? [])
    .filter((p) => p.status === "succeeded")
    .reduce((acc, p) => acc + Number.parseFloat(p.amount), 0);

const invoiceOwed = (inv: InvoiceResponse): number =>
  Math.max(0, Number.parseFloat(inv.total) - settledPaid(inv));

export function rollupInvoices(invoices: InvoiceResponse[]): {
  byCurrency: CurrencyRollup[];
  issuedCount: number;
  hasOwed: boolean;
} {
  const relevant = invoices.filter(
    (i) => i.status === "issued" || i.status === "paid",
  );
  const map = new Map<string, CurrencyRollup>();
  for (const inv of relevant) {
    const row = map.get(inv.currency) ?? {
      currency: inv.currency,
      owed: 0,
      paid: 0,
      billed: 0,
    };
    row.billed += Number.parseFloat(inv.total);
    row.paid += settledPaid(inv);
    if (inv.status === "issued") row.owed += invoiceOwed(inv);
    map.set(inv.currency, row);
  }
  const byCurrency = [...map.values()].sort((a, b) =>
    a.currency.localeCompare(b.currency),
  );
  return {
    byCurrency,
    issuedCount: relevant.filter((i) => i.status === "issued").length,
    hasOwed: byCurrency.some((r) => r.owed > 0.005),
  };
}

export type UnpaidInvoice = { id: string; currency: string; owed: number };

/** The first issued invoice still carrying a balance — the pay deep-link target. */
export function firstUnpaidIssued(invoices: InvoiceResponse[]): UnpaidInvoice | null {
  for (const inv of invoices) {
    if (inv.status !== "issued") continue;
    const owed = invoiceOwed(inv);
    if (owed > 0.005) return { id: inv.id, currency: inv.currency, owed };
  }
  return null;
}

/** Whether an issued invoice is a "what to pay" row (has an outstanding balance). */
export function isPayable(inv: InvoiceResponse): boolean {
  return inv.status === "issued" && invoiceOwed(inv) > 0.005;
}

export { invoiceOwed };

// ── Billing reconciliation + coverage (advisor cockpit, ADV-11) ───────────────
// The advisor's three worries, made visible: (1) "what does each invoice cover?";
// (2) "have I billed everything — and nothing past its cost?"; (3) the money truth
// — trip total (Σ approved node costs, the graph `totals`) reconciled against
// invoiced / paid / outstanding, with the UNINVOICED remainder.
//
// Coverage is AMOUNT-AWARE (D-PAY deposit/balance): a node's cost may be split
// across several charge lines / invoices — a 30% deposit now, the 70% balance
// later — so a node is "covered" only once Σ its (non-void, non-reversed) charge
// lines meets its EFFECTIVE cost (`per_person` × party size). A partially-billed
// node keeps a `remaining` balance and stays billable until the sum closes it out.
// All pure so InvoicePanel and the card badge share one billing truth. NOTE:
// "invoiced" money (Σ invoice totals, including node-less adjustments) and the
// "uninvoiced" node remainder can diverge — we report both, labelled.

/** Structural view of a node for billing — NodeResponse satisfies it. */
export type ChargeableNode = {
  id: string;
  status: string;
  title?: string | undefined;
  cost_amount?: string | null | undefined;
  cost_currency?: string | null | undefined;
  cost_kind?: string | null | undefined;
};

/** An approved node with a cost is chargeable (mirrors InvoicePanel's filter). */
export function isChargeable(n: ChargeableNode): boolean {
  return (
    n.status === "approved" &&
    n.cost_amount != null &&
    n.cost_currency != null &&
    n.cost_currency.length > 0
  );
}

/**
 * A node's EFFECTIVE (billable) cost: a `per_person` quote is expanded by party
 * size, everything else bills at face value. Mirrors the API's
 * `effective_node_cost` so the client's remaining balance — and the amounts it
 * posts for a deposit/balance line — match what the server charges and the money
 * gate reconciles (a drift would break the coverage invariant).
 */
export function effectiveNodeCost(n: ChargeableNode, partySize: number): number {
  const amount = Number.parseFloat(n.cost_amount ?? "0") || 0;
  const size = Math.max(partySize, 1);
  return n.cost_kind === "per_person" ? amount * size : amount;
}

export type NodeCoverage = {
  invoiceId: string;
  label: string;
  status: string;
  /** This charge line's amount toward the node (one entry per covering line). */
  amount: number;
};

/**
 * node_id → the non-void charge lines that bill it, each carrying its amount. A
 * charge line that has been reversed (its id is some reversal line's
 * `reverses_line_item_id`) no longer covers, so it drops out.
 */
export function coverageByNode(
  invoices: InvoiceResponse[],
): Map<string, NodeCoverage[]> {
  const map = new Map<string, NodeCoverage[]>();
  for (const inv of invoices) {
    if (inv.status === "void") continue;
    const lines = inv.lines ?? [];
    const reversedIds = new Set(
      lines
        .map((l) => l.reverses_line_item_id)
        .filter((id): id is string => Boolean(id)),
    );
    for (const line of lines) {
      if (line.kind !== "charge" || !line.node_id) continue;
      if (reversedIds.has(line.id)) continue;
      const arr = map.get(line.node_id) ?? [];
      arr.push({
        invoiceId: inv.id,
        label: inv.label || "Invoice",
        status: inv.status,
        amount: Number.parseFloat(line.amount) || 0,
      });
      map.set(line.node_id, arr);
    }
  }
  return map;
}

/** node_id → Σ its covering charge amounts (the base for its remaining balance). */
export function chargedByNode(invoices: InvoiceResponse[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const [nodeId, cov] of coverageByNode(invoices)) {
    map.set(
      nodeId,
      cov.reduce((sum, c) => sum + c.amount, 0),
    );
  }
  return map;
}

/** A chargeable node with how much of its effective cost is billed vs. remaining. */
export type NodeBilling = {
  id: string;
  title?: string | undefined;
  currency: string;
  /** Party-expanded cost — the full amount that must be billed to cover it. */
  effective: number;
  /** Σ charge lines so far (across every non-void invoice). */
  charged: number;
  /** max(0, effective − charged) — what a balance line would still charge. */
  remaining: number;
  /** The invoices (and amounts) currently charging this node. */
  coverage: NodeCoverage[];
};

/** Sub-cent slack so a fully-billed node reads as covered despite float noise. */
const COVERAGE_EPSILON = 0.005;

export type BillingRow = {
  currency: string;
  /** Σ approved node costs in this currency (the graph `totals`). */
  tripTotal: number;
  /** Σ (issued + paid) invoice totals. */
  invoiced: number;
  /** Σ settled payments. */
  paid: number;
  /** Σ outstanding on issued invoices. */
  outstanding: number;
  /** Σ remaining node balance in this currency — the node cost not yet billed. */
  uninvoiced: number;
  /** # chargeable nodes in this currency with a remaining balance. */
  uninvoicedCount: number;
};

export type BillingSummary = {
  rows: BillingRow[];
  /** Every chargeable node with a remaining balance (fully-billed nodes drop). */
  billableNodes: NodeBilling[];
  coverage: Map<string, NodeCoverage[]>;
  /** ≥1 issued/paid invoice exists AND a node still carries a balance. */
  supplemental: boolean;
};

export function reconcileBilling(input: {
  totals: Record<string, string> | null | undefined;
  invoices: InvoiceResponse[];
  nodes: ChargeableNode[];
  /** Effective traveler count (graph `party_size`); expands `per_person` costs. */
  partySize?: number | undefined;
}): BillingSummary {
  const { invoices, nodes } = input;
  const totals = input.totals ?? {};
  const partySize = input.partySize ?? 1;
  const coverage = coverageByNode(invoices);
  const charged = chargedByNode(invoices);
  const { byCurrency } = rollupInvoices(invoices);
  const rollupByCurrency = new Map(byCurrency.map((r) => [r.currency, r]));

  const chargeable = nodes.filter(isChargeable);
  const billing: NodeBilling[] = chargeable.map((n) => {
    const effective = effectiveNodeCost(n, partySize);
    const paid = charged.get(n.id) ?? 0;
    return {
      id: n.id,
      title: n.title,
      currency: n.cost_currency as string,
      effective,
      charged: paid,
      remaining: Math.max(0, effective - paid),
      coverage: coverage.get(n.id) ?? [],
    };
  });
  const billableNodes = billing.filter((b) => b.remaining > COVERAGE_EPSILON);

  const currencies = new Set<string>([
    ...Object.keys(totals),
    ...byCurrency.map((r) => r.currency),
    ...chargeable.map((n) => n.cost_currency as string),
  ]);

  const rows: BillingRow[] = [...currencies]
    .sort((a, b) => a.localeCompare(b))
    .map((currency) => {
      const tripTotal = Number.parseFloat(totals[currency] ?? "0") || 0;
      const r = rollupByCurrency.get(currency);
      const inCurrency = billableNodes.filter((b) => b.currency === currency);
      return {
        currency,
        tripTotal,
        invoiced: r?.billed ?? 0,
        paid: r?.paid ?? 0,
        outstanding: r?.owed ?? 0,
        uninvoiced: inCurrency.reduce((sum, b) => sum + b.remaining, 0),
        uninvoicedCount: inCurrency.length,
      };
    });

  const hasIssued = invoices.some(
    (i) => i.status === "issued" || i.status === "paid",
  );

  return {
    rows,
    billableNodes,
    coverage,
    supplemental: hasIssued && billableNodes.length > 0,
  };
}

// ── Per-card billing chip (ADV-15) ───────────────────────────────────────────
// The reverse direction of the cockpit: the BOARD shows each card's money state,
// so "how do the invoices relate to the inventory" is readable from either side.
// Pure — the timeline store computes this once per invoices+graph fetch and every
// card wears the result. A card with no cost and no charge wears nothing.

export type BillingChipState = "unbilled" | "partial" | "billed" | "paid";

export type BillingChip = {
  state: BillingChipState;
  /** Deep-link target — the first covering invoice; null while unbilled. */
  invoiceId: string | null;
};

/** Statuses whose money state is an advisor concern (post-approval lifecycle). */
const CHIP_STATUSES = new Set(["approved", "booked", "confirmed"]);

export function billingChipsByNode(input: {
  invoices: InvoiceResponse[];
  nodes: (ChargeableNode & { id: string })[];
  partySize?: number | undefined;
}): Record<string, BillingChip> {
  const partySize = input.partySize ?? 1;
  const coverage = coverageByNode(input.invoices);
  const chips: Record<string, BillingChip> = {};
  for (const node of input.nodes) {
    const cov = coverage.get(node.id) ?? [];
    const priced = node.cost_amount != null && Boolean(node.cost_currency);
    if (cov.length === 0) {
      // Unbilled is only meaningful on a priced card that has entered the
      // bookable lifecycle — a costless or still-proposed card wears nothing.
      if (priced && CHIP_STATUSES.has(node.status)) {
        chips[node.id] = { state: "unbilled", invoiceId: null };
      }
      continue;
    }
    const charged = cov.reduce((sum, c) => sum + c.amount, 0);
    const effective = effectiveNodeCost(node, partySize);
    const invoiceId = cov[0]?.invoiceId ?? null;
    if (effective - charged > COVERAGE_EPSILON && charged > 0) {
      chips[node.id] = { state: "partial", invoiceId };
    } else if (cov.every((c) => c.status === "paid")) {
      chips[node.id] = { state: "paid", invoiceId };
    } else {
      chips[node.id] = { state: "billed", invoiceId };
    }
  }
  return chips;
}

const plural = (n: number, word: string): string =>
  `${n} ${word}${n === 1 ? "" : "s"}`;

// ── Timing summary ───────────────────────────────────────────────────────────
// A human phrase for the trip's dates, honoring the four timing kinds (0033).

type TimingLike = {
  timing_kind?: string | null;
  date_start?: string | null;
  date_end?: string | null;
  duration_nights?: number | null;
  timing_note?: string | null;
};

const fmtDate = (iso: string): string => {
  // ISO date (YYYY-MM-DD) — anchor to local noon so the calendar day never
  // slips across a timezone boundary during formatting.
  const d = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

export function formatTiming(t: TimingLike): string {
  const kind = t.timing_kind ?? null;
  const start = t.date_start ?? null;
  const end = t.date_end ?? null;
  const nights = t.duration_nights ?? null;

  if (kind === "exact" && start && end) return `${fmtDate(start)} – ${fmtDate(end)}`;
  if (kind === "exact" && start) return fmtDate(start);
  if (kind === "window") {
    const span = start && end ? `${fmtDate(start)} – ${fmtDate(end)}` : "A flexible window";
    return nights ? `${span} · about ${plural(nights, "night")}` : span;
  }
  if (kind === "flexible") return t.timing_note?.trim() || "Dates flexible";
  return "Dates to be decided";
}
