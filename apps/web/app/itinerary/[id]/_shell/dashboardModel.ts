// Pure derivations for the per-trip Dashboard (M006/PS3). Kept free of React so
// the two judgement calls the view makes — "what's owed on this trip" and "what's
// the one next best action" — are unit-testable in isolation.

import type { InvoiceResponse } from "@ov-black/api-client";

export type DashboardRole = "advisor" | "client";

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

// ── Next best action ─────────────────────────────────────────────────────────
// The Dashboard's "you're not lost" anchor (design §4): exactly ONE guided action,
// chosen from the trip's real state. The target is either a route (deep-link) or a
// summon of the persistent concierge — the view maps `concierge` to openConcierge().

export type NextActionTarget =
  | { kind: "href"; href: string }
  | { kind: "concierge" };

export type NextAction = {
  label: string;
  detail: string;
  cta: string;
  target: NextActionTarget;
};

const plural = (n: number, word: string): string =>
  `${n} ${word}${n === 1 ? "" : "s"}`;

export function deriveNextAction(input: {
  role: DashboardRole;
  scheduledCount: number;
  pendingCount: number;
  firstUnpaid: UnpaidInvoice | null;
  itineraryId: string;
}): NextAction {
  const { role, scheduledCount, pendingCount, firstUnpaid, itineraryId } = input;
  const timeline = `/itinerary/${itineraryId}/timeline`;
  const owedDetail = (u: UnpaidInvoice): string =>
    `${u.currency} ${u.owed.toFixed(2)} outstanding.`;

  if (role === "advisor") {
    if (pendingCount > 0)
      return {
        label: "Proposals await your review",
        detail: `${plural(pendingCount, "suggestion")} sit on the timeline.`,
        cta: "Open the timeline",
        target: { kind: "href", href: timeline },
      };
    if (scheduledCount === 0)
      return {
        label: "Start shaping the days",
        detail: "Nothing is on the timeline yet.",
        cta: "Open the timeline",
        target: { kind: "href", href: timeline },
      };
    if (firstUnpaid)
      return {
        label: "An invoice awaits payment",
        detail: owedDetail(firstUnpaid),
        cta: "Review the invoice",
        target: { kind: "href", href: `/invoices/${firstUnpaid.id}` },
      };
    return {
      label: "The plan is in good shape",
      detail: "Review the timeline or refine it with the concierge.",
      cta: "Open the timeline",
      target: { kind: "href", href: timeline },
    };
  }

  // Traveler.
  if (firstUnpaid)
    return {
      label: "Settle your balance",
      detail: `${firstUnpaid.currency} ${firstUnpaid.owed.toFixed(2)} due.`,
      cta: "View & pay",
      target: { kind: "href", href: `/invoices/${firstUnpaid.id}` },
    };
  if (scheduledCount === 0)
    return {
      label: "Let’s shape your trip",
      detail: "Tell your concierge what you have in mind.",
      cta: "Talk to your concierge",
      target: { kind: "concierge" },
    };
  if (pendingCount > 0)
    return {
      label: "New ideas to look over",
      detail: `${plural(pendingCount, "suggestion")} from your concierge.`,
      cta: "See the timeline",
      target: { kind: "href", href: timeline },
    };
  return {
    label: "Your trip is taking shape",
    detail: "Explore the timeline or ask your concierge anything.",
    cta: "Talk to your concierge",
    target: { kind: "concierge" },
  };
}

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
