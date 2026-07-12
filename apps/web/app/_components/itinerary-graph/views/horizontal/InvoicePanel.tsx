"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import {
  type InvoiceLineItemResponse,
  type InvoiceResponse,
  type NodeResponse,
  addInvoiceLineItem,
  createApiClient,
  createInvoice,
  getInvoice,
  getItinerary,
  issueInvoice,
  listInvoices,
  voidInvoice,
  voidInvoiceLineItem,
} from "@ov-black/api-client";

import {
  type NodeBilling,
  reconcileBilling,
} from "@/app/itinerary/[id]/_shell/dashboardModel";
import { formatNodeWhen, type TripTimingLike } from "../../model/time";
import { TYPE_TOKENS, type CardKind } from "../../shared/cards/tokens";

// Advisor invoicing surface — the itinerary-aside Invoices tab (M005/I1).
//
// Self-contained like DiffPanel: it takes the staff credentials the store holds
// (travelers never receive them) and calls the invoice wrappers directly. An
// advisor assembles one or more invoices from the itinerary's approved bookable
// nodes, layers signed adjustments (a discount/child line is negative), voids a
// line as an append-only reversal, and issues the invoice. The total is the
// server-computed Σ(lines).

const ATTENTION = "#8b2a1d";

const ERROR_COPY: Record<string, string> = {
  not_found: "This invoice could not be found.",
  advisor_only: "Invoicing is advisor-only.",
  forbidden: "You don't have access to these invoices.",
  invoice_not_draft: "This invoice is issued — only adjustments can be added now.",
  invoice_closed: "This invoice is closed.",
  currency_mismatch: "That line's currency doesn't match the invoice.",
  node_has_no_cost: "That item has no cost to charge.",
  node_overbilled: "That would bill more than the item's remaining cost.",
  already_reversed: "That line was already voided.",
  no_line_items: "Add at least one line before issuing.",
  network_error: "Could not reach the server. Try again in a moment.",
};

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

const ADJUSTMENT_KINDS = ["discount", "adjustment", "tax", "fee"] as const;

const money = (currency: string, amount: number): string => {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${Math.round(amount).toLocaleString()}`;
  }
};

/** Round a major-unit amount to cents (charge lines are always 2dp). */
const round2 = (n: number): number => Math.round(n * 100) / 100;

// ── Card identity, wherever money references it (ADV-15) ─────────────────────
// The invoice ↔ inventory relation was previously only legible as ledger text
// (a line's free-text description). Everywhere money points at a node we now
// render the CARD's identity — type glyph + title deep-linking to the card
// detail + its schedule stamp — so an invoice reads as "which cards, when".

const tokenFor = (type: string) =>
  TYPE_TOKENS[(type in TYPE_TOKENS ? type : "experience") as CardKind];

/** Short schedule stamp — "Wed, Sep 24" pinned, "Day 3" unpinned (Wave E) —
 *  or null while unscheduled (or unpinned with nothing anchoring Day 1). */
const whenStamp = (node: NodeResponse, timing: TripTimingLike | null): string | null => {
  if (!node.starts_at) return null;
  return formatNodeWhen(timing, node.starts_at);
};

function NodeIdentity({
  node,
  itineraryId,
  timing,
  dim = false,
}: {
  node: NodeResponse;
  itineraryId: string;
  timing: TripTimingLike | null;
  dim?: boolean | undefined;
}) {
  const token = tokenFor(node.type);
  const when = whenStamp(node, timing);
  const Icon = token.Icon;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Icon size={12} strokeWidth={1.6} aria-hidden className="shrink-0 text-ink/55" />
      <Link
        href={`/itinerary/${itineraryId}/item/${node.id}`}
        data-testid={`invoice-node-link-${node.id}`}
        className={`min-w-0 truncate font-sans text-sm underline-offset-2 hover:underline ${
          dim ? "text-ink/40 line-through" : "text-ink/90"
        }`}
      >
        {node.title}
      </Link>
      {when ? (
        <span className="shrink-0 font-sans text-[10px] uppercase tracking-[0.12em] text-ink/45">
          {when}
        </span>
      ) : null}
    </span>
  );
}

function Stat({
  label,
  value,
  tone,
  testid,
}: {
  label: string;
  value: string;
  tone?: string | undefined;
  testid?: string | undefined;
}) {
  return (
    <div className="flex flex-col" data-testid={testid}>
      <dt className="text-[9px] uppercase tracking-[0.12em] text-ink/40">{label}</dt>
      <dd className="text-ink/90" style={tone ? { color: tone } : undefined}>
        {value}
      </dd>
    </div>
  );
}

export function InvoicePanel({
  apiBaseUrl,
  accessToken,
  itineraryId,
  canManage,
  heading = true,
}: {
  apiBaseUrl: string | null;
  accessToken: string | null;
  itineraryId: string;
  /** Whether the viewer may write invoices (advisor). Gated on ROLE, not the
   *  graph edit-lock: invoicing is advisor-only server-side and works on any
   *  itinerary status (financial data), so it must not require holding the
   *  draft-only build lock. Non-managers see invoices read-only. */
  canManage: boolean;
  /** Print the panel's own "Invoices" header. Hosts that already title the
   *  surface pass false. */
  heading?: boolean;
}) {
  const [invoices, setInvoices] = useState<InvoiceResponse[]>([]);
  const [nodes, setNodes] = useState<NodeResponse[]>([]);
  const [totals, setTotals] = useState<Record<string, string>>({});
  const [partySize, setPartySize] = useState(1);
  // Trip timing (Wave E): drives the when-stamp rule — real dates once pinned,
  // honest "Day N" ordinals before that.
  const [timing, setTiming] = useState<TripTimingLike | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("Deposit");
  const [newCurrency, setNewCurrency] = useState("USD");
  // Deposit split (blank = bill the whole remaining balance). A value <100 bills
  // that fraction of each node's remaining cost now, leaving the rest for a later
  // balance invoice — the SAME node ends up on both lines (amount-aware coverage).
  const [depositPct, setDepositPct] = useState("");
  const [creating, setCreating] = useState(false);

  // The billing truth: per-node coverage + remaining balance (party-expanded), the
  // billable set, and the per-currency trip-vs-invoiced-vs-paid reconciliation.
  const summary = useMemo(
    () => reconcileBilling({ totals, invoices, nodes, partySize }),
    [totals, invoices, nodes, partySize],
  );
  // Card identity lookup — every money row that references a node renders the
  // card (glyph + linked title + when), not just its ledger description.
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  // A deposit fraction in (0, 1]; blank / out-of-range means the full remainder.
  const depositFraction = useMemo(() => {
    const pct = Number.parseFloat(depositPct);
    if (!Number.isFinite(pct) || pct <= 0 || pct >= 100) return 1;
    return pct / 100;
  }, [depositPct]);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const api =
    apiBaseUrl && accessToken
      ? createApiClient({ baseUrl: apiBaseUrl, accessToken })
      : null;

  const refresh = useCallback(async () => {
    if (!api) return;
    const [inv, graph] = await Promise.all([
      listInvoices(api, itineraryId),
      getItinerary(api, itineraryId),
    ]);
    if (!mounted.current) return;
    if (inv.ok) setInvoices(inv.invoices);
    else setError(copy(inv.detail));
    if (graph.ok) {
      setNodes(graph.nodes);
      setTotals(graph.totals ?? {});
      setPartySize(graph.party_size ?? 1);
      setTiming(graph.itinerary);
    }
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(async () => {
    if (!api || creating) return;
    setCreating(true);
    setError(null);
    try {
      const result = await createInvoice(api, itineraryId, {
        label: newLabel,
        currency: newCurrency.trim().toUpperCase(),
      });
      if (!mounted.current) return;
      if (result.ok) await refresh();
      else setError(copy(result.detail));
    } finally {
      if (mounted.current) setCreating(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, newLabel, newCurrency, creating]);

  // Create a draft, then charge a `fraction` of each node's remaining balance onto
  // it — the one gesture behind "Bill all uninvoiced" (a deposit at <100%, or the
  // full remainder) and "Issue supplemental". Each line posts an explicit amount
  // (fraction × remaining, or the exact remainder when fraction ≥ 1 so a balance
  // closes the node out precisely), tagged to its node so the SAME node can recur
  // across a deposit + balance — amount-aware coverage nets them against its cost.
  const seedInvoice = useCallback(
    async (
      label: string,
      currency: string,
      targets: NodeBilling[],
      fraction: number,
    ) => {
      if (!api || creating || targets.length === 0) return;
      setCreating(true);
      setError(null);
      try {
        const created = await createInvoice(api, itineraryId, { label, currency });
        if (!created.ok) {
          if (mounted.current) setError(copy(created.detail));
          return;
        }
        for (const target of targets) {
          const amount =
            fraction >= 1 ? target.remaining : round2(target.remaining * fraction);
          if (amount <= 0) continue;
          const line = await addInvoiceLineItem(api, created.invoice.id, {
            node_id: target.id,
            kind: "charge",
            amount: amount.toFixed(2),
            currency,
            description: target.title ?? "",
          });
          if (!line.ok) {
            if (mounted.current) setError(copy(line.detail));
            break;
          }
        }
        if (mounted.current) await refresh();
      } finally {
        if (mounted.current) setCreating(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [itineraryId, creating],
  );

  const billableFor = useCallback(
    (currency: string): NodeBilling[] =>
      summary.billableNodes.filter((n) => n.currency === currency),
    [summary],
  );

  return (
    <div
      data-testid="invoice-panel"
      className="flex h-full flex-col gap-5 overflow-y-auto bg-paper px-4 py-4 text-ink"
    >
      {heading ? (
        <header className="flex items-baseline justify-between gap-2">
          <h3 className="font-serif text-lg tracking-tight text-ink">Invoices</h3>
        </header>
      ) : null}

      {/* Reconciliation glance — the money truth the two dashboard sections never
          joined: trip total vs what's invoiced / paid / outstanding, and the
          UNINVOICED remainder (amount + item count) that says "am I done billing". */}
      {loaded && summary.rows.length > 0 ? (
        <section
          data-testid="invoice-reconcile"
          className="flex flex-col gap-2 rounded-lg border border-ink/10 bg-ink/[0.02] px-3 py-3"
        >
          {summary.rows.map((row) => (
            <div
              key={row.currency}
              data-testid="invoice-reconcile-row"
              data-currency={row.currency}
              className="flex flex-col gap-1"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-sans text-[10px] uppercase tracking-[0.18em] text-ink/45">
                  {row.currency}
                </span>
                <span
                  data-testid="reconcile-trip-total"
                  className="font-serif text-base tabular-nums text-ink"
                >
                  {money(row.currency, row.tripTotal)}
                  <span className="ml-1 text-[10px] uppercase tracking-[0.14em] text-ink/45">
                    trip
                  </span>
                </span>
              </div>
              <dl className="grid grid-cols-4 gap-1 font-sans text-[11px] tabular-nums">
                <Stat label="Invoiced" value={money(row.currency, row.invoiced)} />
                <Stat label="Paid" value={money(row.currency, row.paid)} />
                <Stat
                  label="Outstanding"
                  value={money(row.currency, row.outstanding)}
                  tone={row.outstanding > 0.005 ? ATTENTION : undefined}
                />
                <Stat
                  label={`Uninvoiced${row.uninvoicedCount > 0 ? ` · ${row.uninvoicedCount}` : ""}`}
                  value={money(row.currency, row.uninvoiced)}
                  tone={row.uninvoiced > 0.005 ? "#8a5a1d" : undefined}
                  testid="reconcile-uninvoiced"
                />
              </dl>
            </div>
          ))}
        </section>
      ) : null}

      {/* The unbilled items THEMSELVES (ADV-15) — the reconcile strip's
          "uninvoiced" number expanded into identifiable inventory: which cards,
          when, and how much each still carries. The pointable answer to "am I
          done billing". */}
      {canManage && loaded && summary.billableNodes.length > 0 ? (
        <section
          data-testid="invoice-unbilled"
          className="flex flex-col gap-1.5 rounded-lg border border-[#8a5a1d]/25 bg-paper px-3 py-3"
        >
          <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-[#8a5a1d]">
            Not yet billed
          </span>
          <ul className="flex flex-col divide-y divide-ink/5">
            {summary.billableNodes.map((b) => {
              const node = nodeById.get(b.id);
              return (
                <li
                  key={b.id}
                  data-testid={`invoice-unbilled-${b.id}`}
                  className="flex items-center gap-3 py-1.5"
                >
                  <span className="min-w-0 flex-1">
                    {node ? (
                      <NodeIdentity node={node} itineraryId={itineraryId} timing={timing} />
                    ) : (
                      <span className="min-w-0 truncate font-sans text-sm text-ink/90">
                        {b.title}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 font-sans text-sm tabular-nums text-ink/80">
                    {money(b.currency, b.remaining)}
                    {b.charged > 0 ? (
                      <span className="ml-1 font-sans text-[10px] uppercase tracking-[0.12em] text-ink/45">
                        of {money(b.currency, b.effective)}
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {/* Supplemental prompt — items became chargeable after an invoice went out;
          offer a pre-seeded supplemental over exactly the uncovered nodes. */}
      {canManage && summary.supplemental ? (
        <section
          data-testid="invoice-supplemental"
          className="flex flex-col gap-2 rounded-lg border border-[#8a5a1d]/30 bg-[#8a5a1d]/[0.06] px-3 py-3"
        >
          <p className="font-sans text-xs text-ink/80">
            {summary.billableNodes.length === 1
              ? "1 chargeable item still has an unbilled balance."
              : `${summary.billableNodes.length} chargeable items still have an unbilled balance.`}{" "}
            Issue a supplemental to cover them.
          </p>
          <div className="flex flex-wrap gap-2">
            {summary.rows
              .filter((r) => r.uninvoicedCount > 0)
              .map((r) => (
                <button
                  key={r.currency}
                  type="button"
                  onClick={() =>
                    void seedInvoice("Supplemental", r.currency, billableFor(r.currency), 1)
                  }
                  disabled={creating}
                  data-testid="invoice-supplemental-issue"
                  data-currency={r.currency}
                  className="rounded-md border border-[#8a5a1d]/40 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.18em] text-[#8a5a1d] transition-colors hover:bg-[#8a5a1d]/10 disabled:opacity-40"
                >
                  Issue supplemental · {r.currency} ({r.uninvoicedCount})
                </button>
              ))}
          </div>
        </section>
      ) : null}

      {/* New invoice */}
      {canManage ? (
        <section className="flex flex-col gap-2 border-y border-ink/10 py-3">
          <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
            New invoice
          </span>
          <div className="flex items-center gap-2">
            <input
              aria-label="Invoice label"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper-white px-2 py-1 font-sans text-sm text-ink"
            />
            <input
              aria-label="Invoice currency"
              value={newCurrency}
              onChange={(e) => setNewCurrency(e.target.value)}
              maxLength={3}
              className="w-16 rounded-md border border-ink/20 bg-paper-white px-2 py-1 font-sans text-sm uppercase text-ink"
            />
            <button
              type="button"
              onClick={() => void create()}
              disabled={creating}
              data-testid="invoice-create"
              className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
          {/* Deposit split: bill a % of each node's remaining now, the rest later.
              Blank = the whole remaining balance. */}
          <label className="flex items-center gap-2 font-sans text-[11px] text-ink/60">
            <span className="uppercase tracking-[0.14em] text-ink/45">Deposit %</span>
            <input
              aria-label="Deposit percent"
              inputMode="decimal"
              placeholder="100"
              value={depositPct}
              onChange={(e) => setDepositPct(e.target.value)}
              data-testid="invoice-deposit-pct"
              className="w-16 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-right tabular-nums text-ink"
            />
            <span className="text-ink/45">of each item now (blank = full balance)</span>
          </label>
          {/* One-click: a draft charging every chargeable node with a balance, at
              the deposit % (or its full remainder). The fast path to an invoice. */}
          {billableFor(newCurrency.trim().toUpperCase()).length > 0 ? (
            <button
              type="button"
              onClick={() =>
                void seedInvoice(
                  newLabel || "Invoice",
                  newCurrency.trim().toUpperCase(),
                  billableFor(newCurrency.trim().toUpperCase()),
                  depositFraction,
                )
              }
              disabled={creating}
              data-testid="invoice-bill-all"
              className="self-start rounded-md border border-ink/20 bg-ink px-3 py-1 font-sans text-[10px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {depositFraction < 1
                ? `Bill ${Math.round(depositFraction * 100)}% deposit (${billableFor(newCurrency.trim().toUpperCase()).length})`
                : `Bill all remaining (${billableFor(newCurrency.trim().toUpperCase()).length})`}
            </button>
          ) : null}
        </section>
      ) : (
        <p className="font-sans text-xs italic text-ink/50">
          Your advisor manages invoicing for this trip.
        </p>
      )}

      {!loaded ? (
        <p className="font-sans text-sm text-ink/50">Loading…</p>
      ) : invoices.length === 0 ? (
        <p className="font-sans text-sm italic text-ink/50">
          No invoices yet. Create one over the approved bookable nodes.
        </p>
      ) : (
        invoices.map((invoice) => (
          <InvoiceCard
            key={invoice.id}
            invoice={invoice}
            itineraryId={itineraryId}
            nodeById={nodeById}
            timing={timing}
            billableNodes={summary.billableNodes}
            canManage={canManage}
            api={api}
            onChanged={refresh}
            onError={setError}
          />
        ))
      )}

      {error ? (
        <p role="alert" className="font-sans text-xs font-medium" style={{ color: ATTENTION }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  draft: "text-ink/55",
  issued: "text-[#1d4e8b]",
  paid: "text-[#1d6b3a]",
  void: "text-ink/40 line-through",
};

function InvoiceCard({
  invoice,
  itineraryId,
  nodeById,
  timing,
  billableNodes,
  canManage,
  api,
  onChanged,
  onError,
}: {
  invoice: InvoiceResponse;
  itineraryId: string;
  nodeById: Map<string, NodeResponse>;
  timing: TripTimingLike | null;
  billableNodes: NodeBilling[];
  canManage: boolean;
  api: ReturnType<typeof createApiClient> | null;
  onChanged: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [adjKind, setAdjKind] = useState<(typeof ADJUSTMENT_KINDS)[number]>(
    "discount",
  );
  const [adjAmount, setAdjAmount] = useState("");
  const [adjDesc, setAdjDesc] = useState("");
  // Per-node charge: pick a node, then optionally type an explicit amount (blank =
  // its full remaining balance). The two-input form so a deposit can be a precise
  // figure, not only the panel's whole-invoice %.
  const [chargeNodeId, setChargeNodeId] = useState("");
  const [chargeAmount, setChargeAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const lines = invoice.lines ?? [];
  const reversedIds = new Set(
    lines
      .map((l) => l.reverses_line_item_id)
      .filter((id): id is string => Boolean(id)),
  );
  const open = invoice.status === "draft" || invoice.status === "issued";
  const canWrite = canManage && open && api !== null;

  const run = useCallback(
    async (fn: () => Promise<{ ok: boolean; detail?: string }>) => {
      if (busy) return;
      setBusy(true);
      onError(null);
      try {
        const result = await fn();
        if (result.ok) await onChanged();
        else onError(copy(result.detail ?? "unknown"));
      } finally {
        setBusy(false);
      }
    },
    [busy, onChanged, onError],
  );

  // Charge the picked node: an explicit typed amount if given (a precise deposit),
  // else its FULL remaining balance (the "balance" action, closing it to zero).
  // Either way it's tagged to the node, so it nets against the node's cost. The
  // server guards a charge that would exceed the node's remaining.
  const submitCharge = (target: NodeBilling | null) => {
    if (!api || !target) return;
    const typed = chargeAmount.trim();
    const amount = typed ? round2(Number.parseFloat(typed)) : target.remaining;
    if (!Number.isFinite(amount) || amount <= 0) return;
    void run(() =>
      addInvoiceLineItem(api, invoice.id, {
        node_id: target.id,
        kind: "charge",
        amount: amount.toFixed(2),
        currency: invoice.currency,
        description: target.title ?? "",
      }),
    ).then(() => {
      setChargeNodeId("");
      setChargeAmount("");
    });
  };

  const addAdjustment = () => {
    if (!api || !adjAmount.trim()) return;
    void run(() =>
      addInvoiceLineItem(api, invoice.id, {
        kind: adjKind,
        description: adjDesc,
        amount: adjAmount.trim(),
        currency: invoice.currency,
      }),
    ).then(() => {
      setAdjAmount("");
      setAdjDesc("");
    });
  };

  // Nodes with a remaining balance in this currency — a partially-billed node
  // stays here (its balance line closes it out) until fully covered.
  const candidates = billableNodes.filter((n) => n.currency === invoice.currency);
  const chargeTarget = candidates.find((c) => c.id === chargeNodeId) ?? null;

  return (
    <section
      data-testid={`invoice-${invoice.id}`}
      className="flex flex-col gap-2 border-b border-ink/10 pb-4"
    >
      <header className="flex items-baseline justify-between gap-2">
        <span className="font-serif text-base text-ink">{invoice.label || "Invoice"}</span>
        <span className="flex items-baseline gap-2">
          <span
            className={`font-sans text-[10px] uppercase tracking-[0.18em] ${
              STATUS_TONE[invoice.status] ?? "text-ink/55"
            }`}
          >
            {invoice.status}
          </span>
          <span className="font-sans text-sm tabular-nums text-ink" data-testid="invoice-total">
            {invoice.total} {invoice.currency}
          </span>
        </span>
      </header>

      {lines.length === 0 ? (
        <p className="font-sans text-xs italic text-ink/45">No lines yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
          {lines.map((line) => (
            <LineRow
              key={line.id}
              line={line}
              node={line.node_id ? (nodeById.get(line.node_id) ?? null) : null}
              itineraryId={itineraryId}
              timing={timing}
              reversed={reversedIds.has(line.id)}
              canWrite={canWrite}
              onVoid={() =>
                api &&
                void run(() => voidInvoiceLineItem(api, invoice.id, line.id))
              }
            />
          ))}
        </ul>
      )}

      {canWrite ? (
        <div className="flex flex-col gap-2 pt-1">
          {/* Charge a node (draft only): pick it, optionally type an amount (blank
              = its full remaining balance), then Add. Explicit amounts let a
              deposit be a precise figure per node; the panel's Deposit % does it
              in bulk. */}
          {invoice.status === "draft" && candidates.length > 0 ? (
            <div className="flex items-center gap-1.5 font-sans text-xs text-ink/70">
              <span className="shrink-0 uppercase tracking-[0.14em] text-ink/45">
                Charge
              </span>
              <select
                aria-label="Charge a node"
                data-testid="invoice-charge-node"
                value={chargeNodeId}
                onChange={(e) => setChargeNodeId(e.target.value)}
                className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-sm text-ink"
              >
                <option value="" disabled>
                  Add a node charge…
                </option>
                {candidates.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title} · {money(n.currency, n.remaining)}
                    {n.charged > 0 ? " remaining" : ""}
                  </option>
                ))}
              </select>
              <input
                aria-label="Charge amount"
                placeholder={chargeTarget ? chargeTarget.remaining.toFixed(2) : "amount"}
                value={chargeAmount}
                onChange={(e) => setChargeAmount(e.target.value)}
                className="w-24 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-right tabular-nums text-ink"
              />
              <button
                type="button"
                onClick={() => submitCharge(chargeTarget)}
                disabled={busy || !chargeTarget}
                data-testid="invoice-charge-node-add"
                className="rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
              >
                Add
              </button>
            </div>
          ) : null}

          {/* Signed adjustment (discount / child / tax / fee) */}
          <div className="flex items-center gap-1.5">
            <select
              aria-label="Adjustment kind"
              value={adjKind}
              onChange={(e) =>
                setAdjKind(e.target.value as (typeof ADJUSTMENT_KINDS)[number])
              }
              className="rounded-md border border-ink/20 bg-paper-white px-1.5 py-1 text-xs text-ink"
            >
              {ADJUSTMENT_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <input
              aria-label="Adjustment description"
              placeholder="e.g. Child discount"
              value={adjDesc}
              onChange={(e) => setAdjDesc(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-xs text-ink"
            />
            <input
              aria-label="Adjustment amount"
              placeholder="-250.00"
              value={adjAmount}
              onChange={(e) => setAdjAmount(e.target.value)}
              className="w-24 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-right text-xs tabular-nums text-ink"
            />
            <button
              type="button"
              onClick={addAdjustment}
              disabled={busy}
              data-testid="invoice-add-adjustment"
              className="rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Add
            </button>
          </div>

          <div className="flex items-center gap-2 pt-1">
            {invoice.status === "draft" ? (
              <button
                type="button"
                onClick={() =>
                  api && void run(() => issueInvoice(api, invoice.id))
                }
                disabled={busy}
                data-testid="invoice-issue"
                className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
              >
                Issue
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => api && void run(() => voidInvoice(api, invoice.id))}
              disabled={busy}
              data-testid="invoice-void"
              className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/70 transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Void invoice
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function LineRow({
  line,
  node,
  itineraryId,
  timing,
  reversed,
  canWrite,
  onVoid,
}: {
  line: InvoiceLineItemResponse;
  /** The card this line charges, when it's a node-tagged line (ADV-15). */
  node: NodeResponse | null;
  itineraryId: string;
  timing: TripTimingLike | null;
  reversed: boolean;
  canWrite: boolean;
  onVoid: () => void;
}) {
  const isReversal = line.kind === "reversal";
  const negative = Number(line.amount) < 0;
  return (
    <li className="flex items-center gap-3 py-2" data-testid={`line-${line.id}`}>
      <div className="min-w-0 flex-1">
        {node ? (
          // A node-tagged line reads as the CARD it charges — glyph + linked
          // title + schedule stamp — not as ledger prose.
          <NodeIdentity
            node={node}
            itineraryId={itineraryId}
            timing={timing}
            dim={reversed}
          />
        ) : (
          <p
            className={`truncate font-sans text-sm ${
              reversed ? "text-ink/40 line-through" : "text-ink/90"
            }`}
          >
            {line.description || line.kind}
          </p>
        )}
        <p className="font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45">
          {line.kind}
        </p>
      </div>
      <span
        className={`shrink-0 font-sans text-sm tabular-nums ${
          negative ? "text-[#8b2a1d]" : "text-ink/90"
        }`}
      >
        {line.amount} {line.currency}
      </span>
      {canWrite && !isReversal && !reversed ? (
        <button
          type="button"
          onClick={onVoid}
          data-testid={`line-void-${line.id}`}
          className="shrink-0 rounded-md border border-ink/15 px-2 py-0.5 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/55 transition-colors hover:bg-ink/5"
        >
          Void
        </button>
      ) : null}
    </li>
  );
}
