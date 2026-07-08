"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type NodeResponse,
  type OfferResponse,
  type ReconciliationResponse,
  bookNode,
  cancelBooking,
  confirmNode,
  createApiClient,
  getItinerary,
  getReconciliation,
  refreshOffer,
} from "@ov-black/api-client";

import { copy } from "./bookingCopy";
import { SupplierSlotPickerDialog } from "./SupplierSlotPickerDialog";

// Advisor booking surface — the dashboard Booking tab (M005/I3).
//
// Self-contained like InvoicePanel: it takes the staff credentials the store
// holds and calls the booking wrappers directly. The money gate lives on the
// server — an approved node books only when a covering PAID invoice line exists
// (an explicit override books on a merely issued line). Flights re-price their
// held offer first. A booked node advances to confirmed with a supplier ref. The
// reconciliation banner reads the server invariant: Σ(paid lines) ⇔ Σ(booked).
//
// Like invoicing (ADV-11), booking is financial workflow independent of the
// graph edit-lock: it must work on a proposed/approved trip, where the build is
// frozen — so it gates on advisor role (`canManage`), never `selectEditable`
// (which requires a draft + the held lock and would hide every action exactly
// when a node is bookable). ADV-12.

const ATTENTION = "#8b2a1d";
const OK = "#1d6b3a";

const BOOKABLE_TYPES = new Set(["flight", "hotel", "experience", "meal"]);

// Sources that can be booked live through the supplier (reserve + confirm). Only
// Bokun today; the server still gates on its own feature flag + credentials, and
// the slot dialog falls back to a manual book when that gate is closed.
const SUPPLIER_BOOKABLE_SOURCES = new Set(["bokun"]);

function bookableNodes(nodes: NodeResponse[]): NodeResponse[] {
  return nodes
    .filter(
      (n) =>
        BOOKABLE_TYPES.has(n.type) &&
        (n.status === "approved" || n.status === "booked" || n.status === "confirmed"),
    )
    .sort((a, b) => a.title.localeCompare(b.title));
}

const STATUS_TONE: Record<string, string> = {
  approved: "text-[#1d4e8b]",
  booked: "text-[#1d6b3a]",
  confirmed: "text-[#1d6b3a] font-semibold",
};

export function BookingPanel({
  apiBaseUrl,
  accessToken,
  itineraryId,
  canManage,
}: {
  apiBaseUrl: string | null;
  accessToken: string | null;
  itineraryId: string;
  canManage: boolean;
}) {
  const [nodes, setNodes] = useState<NodeResponse[]>([]);
  const [recon, setRecon] = useState<ReconciliationResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    const [graph, rec] = await Promise.all([
      getItinerary(api, itineraryId),
      getReconciliation(api, itineraryId),
    ]);
    if (!mounted.current) return;
    if (graph.ok) setNodes(graph.nodes);
    else setError(copy(graph.detail));
    if (rec.ok) setRecon(rec.reconciliation);
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const candidates = bookableNodes(nodes);

  return (
    <div
      data-testid="booking-panel"
      className="flex h-full flex-col gap-5 overflow-y-auto bg-paper px-4 py-4 text-ink"
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="font-serif text-lg tracking-tight text-ink">Booking</h3>
      </header>

      {recon ? <ReconciliationBanner recon={recon} /> : null}

      {!canManage ? (
        <p className="font-sans text-xs italic text-ink/50">
          Booking is managed by your advisor.
        </p>
      ) : null}

      {!loaded ? (
        <p className="font-sans text-sm text-ink/50">Loading…</p>
      ) : candidates.length === 0 ? (
        <p className="font-sans text-sm italic text-ink/50">
          No approved bookable items yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
          {candidates.map((node) => (
            <BookingRow
              key={node.id}
              node={node}
              itineraryId={itineraryId}
              canManage={canManage}
              api={api}
              onChanged={refresh}
              onError={setError}
            />
          ))}
        </ul>
      )}

      {error ? (
        <p role="alert" className="font-sans text-xs font-medium" style={{ color: ATTENTION }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ReconciliationBanner({ recon }: { recon: ReconciliationResponse }) {
  const rows = recon.rows ?? [];
  const violations = recon.violations ?? [];
  return (
    <section
      data-testid="reconciliation-banner"
      className="flex flex-col gap-1 border-y border-ink/10 py-3"
    >
      <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
        Reconciliation
      </span>
      {recon.balanced ? (
        <p
          data-testid="reconciliation-status"
          className="font-sans text-sm font-medium"
          style={{ color: OK }}
        >
          Reconciled ✓ — Σ paid equals Σ booked.
        </p>
      ) : (
        <p
          data-testid="reconciliation-status"
          className="font-sans text-sm font-medium"
          style={{ color: ATTENTION }}
        >
          Not reconciled — {violations.length} discrepanc
          {violations.length === 1 ? "y" : "ies"}.
        </p>
      )}
      {rows.map((r) => (
        <p
          key={r.currency}
          className="font-sans text-xs tabular-nums text-ink/70"
        >
          {r.currency}: paid {r.paid_total} · booked {r.booked_total}
          {r.balanced ? "" : " ⚠"}
        </p>
      ))}
    </section>
  );
}

function BookingRow({
  node,
  itineraryId,
  canManage,
  api,
  onChanged,
  onError,
}: {
  node: NodeResponse;
  itineraryId: string;
  canManage: boolean;
  api: ReturnType<typeof createApiClient> | null;
  onChanged: () => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [override, setOverride] = useState(false);
  const [offer, setOffer] = useState<OfferResponse | null>(null);
  const [ref, setRef] = useState("");
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const canWrite = canManage && api !== null;
  const isFlight = node.type === "flight";
  const isSupplierBookable = node.source != null && SUPPLIER_BOOKABLE_SOURCES.has(node.source);

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

  const reprice = () => {
    if (!api) return;
    void (async () => {
      setBusy(true);
      onError(null);
      try {
        const result = await refreshOffer(api, itineraryId, node.id);
        if (result.ok) setOffer(result.offer);
        else onError(copy(result.detail));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <li
      data-testid={`booking-${node.id}`}
      className="flex flex-col gap-2 py-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 flex-1 truncate font-sans text-sm text-ink/90">
          {node.title}
        </span>
        <span
          className={`shrink-0 font-sans text-[10px] uppercase tracking-[0.16em] ${
            STATUS_TONE[node.status] ?? "text-ink/55"
          }`}
        >
          {node.status}
        </span>
        {node.cost_amount != null ? (
          <span className="shrink-0 font-sans text-sm tabular-nums text-ink/80">
            {node.cost_amount} {node.cost_currency}
          </span>
        ) : null}
      </div>

      {offer ? (
        <p className="font-sans text-xs tabular-nums text-ink/60" data-testid={`offer-${node.id}`}>
          Held fare: {offer.amount} {offer.currency}
        </p>
      ) : null}

      {canWrite && node.status === "approved" ? (
        <div className="flex flex-wrap items-center gap-2">
          {isFlight ? (
            <button
              type="button"
              onClick={reprice}
              disabled={busy}
              data-testid={`reprice-${node.id}`}
              className="rounded-md border border-ink/20 bg-paper px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Re-price
            </button>
          ) : null}
          {isSupplierBookable ? (
            <button
              type="button"
              onClick={() => setPickerOpen(true)}
              disabled={busy}
              data-testid={`book-slot-${node.id}`}
              className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Choose slot &amp; book
            </button>
          ) : (
            <button
              type="button"
              onClick={() =>
                api &&
                void run(() =>
                  bookNode(api, itineraryId, node.id, { override_unpaid: override }),
                )
              }
              disabled={busy}
              data-testid={`book-${node.id}`}
              className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Book
            </button>
          )}
          <label className="flex items-center gap-1 font-sans text-[10px] uppercase tracking-[0.12em] text-ink/55">
            <input
              type="checkbox"
              checked={override}
              onChange={(e) => setOverride(e.target.checked)}
              data-testid={`override-${node.id}`}
            />
            Override (issued)
          </label>
        </div>
      ) : null}

      {pickerOpen && api ? (
        <SupplierSlotPickerDialog
          api={api}
          itineraryId={itineraryId}
          node={node}
          overrideUnpaid={override}
          onBooked={onChanged}
          onClose={() => setPickerOpen(false)}
        />
      ) : null}

      {canWrite && node.status === "booked" ? (
        <div className="flex items-center gap-2">
          <input
            aria-label="Supplier confirmation #"
            placeholder="Confirmation # / PNR"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            data-testid={`confirm-ref-${node.id}`}
            className="min-w-0 flex-1 rounded-md border border-ink/20 bg-paper px-2 py-1 font-sans text-sm text-ink"
          />
          <button
            type="button"
            onClick={() =>
              api &&
              ref.trim() &&
              void run(() =>
                confirmNode(api, itineraryId, node.id, { supplier_ref: ref.trim() }),
              )
            }
            disabled={busy || !ref.trim()}
            data-testid={`confirm-${node.id}`}
            className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
          >
            Confirm
          </button>
        </div>
      ) : null}

      {canWrite && (node.status === "booked" || node.status === "confirmed") ? (
        <div className="flex flex-wrap items-center gap-2">
          {confirmingCancel ? (
            <>
              <span className="font-sans text-[11px] text-ink/70">
                Refund {node.cost_amount ?? ""} {node.cost_currency ?? ""} and cancel this booking?
              </span>
              <button
                type="button"
                onClick={() =>
                  api && void run(() => cancelBooking(api, itineraryId, node.id, {}))
                }
                disabled={busy}
                data-testid={`cancel-confirm-${node.id}`}
                className="rounded-md border bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] transition-colors hover:bg-ink/5 disabled:opacity-40"
                style={{ borderColor: ATTENTION, color: ATTENTION }}
              >
                Confirm refund
              </button>
              <button
                type="button"
                onClick={() => setConfirmingCancel(false)}
                disabled={busy}
                data-testid={`cancel-abort-${node.id}`}
                className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55 hover:text-ink"
              >
                Keep
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingCancel(true)}
              disabled={busy}
              data-testid={`cancel-${node.id}`}
              className="rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Cancel booking
            </button>
          )}
        </div>
      ) : null}
    </li>
  );
}
