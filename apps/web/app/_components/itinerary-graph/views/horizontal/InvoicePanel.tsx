"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  type ChargeableNode,
  reconcileBilling,
} from "@/app/itinerary/[id]/_shell/dashboardModel";

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
  editable,
  heading = true,
}: {
  apiBaseUrl: string | null;
  accessToken: string | null;
  itineraryId: string;
  editable: boolean;
  /** Print the panel's own "Invoices" header. Hosts that already title the
   *  surface (the toolbar modal) pass false. */
  heading?: boolean;
}) {
  const [invoices, setInvoices] = useState<InvoiceResponse[]>([]);
  const [nodes, setNodes] = useState<NodeResponse[]>([]);
  const [totals, setTotals] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("Deposit");
  const [newCurrency, setNewCurrency] = useState("USD");
  const [creating, setCreating] = useState(false);

  // The billing truth: coverage (which node is on which invoice), the uninvoiced
  // remainder, and the per-currency trip-vs-invoiced-vs-paid reconciliation.
  const summary = useMemo(
    () => reconcileBilling({ totals, invoices, nodes }),
    [totals, invoices, nodes],
  );

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

  // Create a draft, then charge each node onto it — the one gesture behind both
  // "Bill all uninvoiced" (first/balance invoice) and "Issue supplemental" (the
  // delta since the last issued invoice). One coherent model: invoices partition
  // the trip's chargeable nodes, so a node is billed on exactly one of them.
  const seedInvoice = useCallback(
    async (label: string, currency: string, nodeIds: string[]) => {
      if (!api || creating || nodeIds.length === 0) return;
      setCreating(true);
      setError(null);
      try {
        const created = await createInvoice(api, itineraryId, { label, currency });
        if (!created.ok) {
          if (mounted.current) setError(copy(created.detail));
          return;
        }
        for (const nodeId of nodeIds) {
          const line = await addInvoiceLineItem(api, created.invoice.id, {
            node_id: nodeId,
            kind: "charge",
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

  const uninvoicedIdsFor = useCallback(
    (currency: string): string[] =>
      summary.uninvoicedNodes
        .filter((n) => n.cost_currency === currency)
        .map((n) => n.id),
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

      {/* Supplemental prompt — items became chargeable after an invoice went out;
          offer a pre-seeded supplemental over exactly the uncovered nodes. */}
      {editable && summary.supplemental ? (
        <section
          data-testid="invoice-supplemental"
          className="flex flex-col gap-2 rounded-lg border border-[#8a5a1d]/30 bg-[#8a5a1d]/[0.06] px-3 py-3"
        >
          <p className="font-sans text-xs text-ink/80">
            {summary.uninvoicedNodes.length === 1
              ? "1 chargeable item isn’t on any invoice yet."
              : `${summary.uninvoicedNodes.length} chargeable items aren’t on any invoice yet.`}{" "}
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
                    void seedInvoice("Supplemental", r.currency, uninvoicedIdsFor(r.currency))
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
      {editable ? (
        <section className="flex flex-col gap-2 border-y border-ink/10 py-3">
          <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
            New invoice
          </span>
          <div className="flex items-center gap-2">
            <input
              aria-label="Invoice label"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-sm text-ink"
            />
            <input
              aria-label="Invoice currency"
              value={newCurrency}
              onChange={(e) => setNewCurrency(e.target.value)}
              maxLength={3}
              className="w-16 rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-sm uppercase text-ink"
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
          {/* One-click: a draft covering every chargeable node not yet on an
              invoice, in the entered currency. The fast path to the first invoice. */}
          {uninvoicedIdsFor(newCurrency.trim().toUpperCase()).length > 0 ? (
            <button
              type="button"
              onClick={() =>
                void seedInvoice(
                  newLabel || "Invoice",
                  newCurrency.trim().toUpperCase(),
                  uninvoicedIdsFor(newCurrency.trim().toUpperCase()),
                )
              }
              disabled={creating}
              data-testid="invoice-bill-all"
              className="self-start rounded-md border border-ink/20 bg-ink px-3 py-1 font-sans text-[10px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              Bill all uninvoiced ({uninvoicedIdsFor(newCurrency.trim().toUpperCase()).length})
            </button>
          ) : null}
        </section>
      ) : (
        <p className="font-sans text-xs italic text-ink/50">
          Hold the edit lock to assemble invoices.
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
            uninvoicedNodes={summary.uninvoicedNodes}
            editable={editable}
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
  uninvoicedNodes,
  editable,
  api,
  onChanged,
  onError,
}: {
  invoice: InvoiceResponse;
  uninvoicedNodes: ChargeableNode[];
  editable: boolean;
  api: ReturnType<typeof createApiClient> | null;
  onChanged: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [adjKind, setAdjKind] = useState<(typeof ADJUSTMENT_KINDS)[number]>(
    "discount",
  );
  const [adjAmount, setAdjAmount] = useState("");
  const [adjDesc, setAdjDesc] = useState("");
  const [busy, setBusy] = useState(false);

  const lines = invoice.lines ?? [];
  const reversedIds = new Set(
    lines
      .map((l) => l.reverses_line_item_id)
      .filter((id): id is string => Boolean(id)),
  );
  const open = invoice.status === "draft" || invoice.status === "issued";
  const canWrite = editable && open && api !== null;

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

  const chargeNode = (nodeId: string) => {
    if (!api || !nodeId) return;
    void run(() =>
      addInvoiceLineItem(api, invoice.id, { node_id: nodeId, kind: "charge" }),
    );
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

  // Only nodes not already on any invoice — the picker can't double-charge.
  const candidates = uninvoicedNodes.filter(
    (n) => n.cost_currency === invoice.currency,
  );

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
          {/* Charge an approved node's cost (draft only) */}
          {invoice.status === "draft" && candidates.length > 0 ? (
            <label className="flex items-center gap-2 font-sans text-xs text-ink/70">
              <span className="shrink-0 uppercase tracking-[0.14em] text-ink/45">
                Charge
              </span>
              <select
                aria-label="Charge a node"
                data-testid="invoice-charge-node"
                defaultValue=""
                onChange={(e) => {
                  chargeNode(e.target.value);
                  e.target.value = "";
                }}
                className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper px-2 py-1 text-sm text-ink"
              >
                <option value="" disabled>
                  Add a node charge…
                </option>
                {candidates.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.title} · {n.cost_currency} {n.cost_amount}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          {/* Signed adjustment (discount / child / tax / fee) */}
          <div className="flex items-center gap-1.5">
            <select
              aria-label="Adjustment kind"
              value={adjKind}
              onChange={(e) =>
                setAdjKind(e.target.value as (typeof ADJUSTMENT_KINDS)[number])
              }
              className="rounded-md border border-ink/20 bg-paper px-1.5 py-1 text-xs text-ink"
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
              className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper px-2 py-1 text-xs text-ink"
            />
            <input
              aria-label="Adjustment amount"
              placeholder="-250.00"
              value={adjAmount}
              onChange={(e) => setAdjAmount(e.target.value)}
              className="w-24 rounded-md border border-ink/20 bg-paper px-2 py-1 text-right text-xs tabular-nums text-ink"
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
  reversed,
  canWrite,
  onVoid,
}: {
  line: InvoiceLineItemResponse;
  reversed: boolean;
  canWrite: boolean;
  onVoid: () => void;
}) {
  const isReversal = line.kind === "reversal";
  const negative = Number(line.amount) < 0;
  return (
    <li className="flex items-center gap-3 py-2" data-testid={`line-${line.id}`}>
      <div className="min-w-0 flex-1">
        <p
          className={`truncate font-sans text-sm ${
            reversed ? "text-ink/40 line-through" : "text-ink/90"
          }`}
        >
          {line.description || line.kind}
        </p>
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
