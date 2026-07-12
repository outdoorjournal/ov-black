"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type NodeResponse,
  type SupplierAvailabilityResponse,
  type SupplierSelectionRequest,
  bookNode,
  createApiClient,
  supplierAvailability,
} from "@ov-black/api-client";

import { copy } from "./bookingCopy";

// Real supplier booking (Bokun) — the advisor's slot picker (M005/I3 + 0034).
//
// A Bokun-sourced node can't just "Book": Bokun holds inventory against a
// specific availability (date + start-time + rate) and a per-category
// participant breakdown. This dialog fetches the node's live availability, lets
// the advisor pick a slot + counts, and books it through the money gate — the
// server reserves + confirms upstream and stores the confirmation code. When the
// supplier path isn't enabled (or has no live availability), a fallback books
// the node the manual way so the advisor is never stranded.

type Api = ReturnType<typeof createApiClient>;

const AVAILABILITY_WINDOW_DAYS = 90;

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function slotKey(s: SupplierAvailabilityResponse): string {
  return `${s.availability_id}|${s.rate_id ?? ""}|${s.start_time_id ?? ""}`;
}

function slotLabel(s: SupplierAvailabilityResponse): string {
  const time = s.start_time ? ` · ${s.start_time}` : "";
  const seats = s.seats_available != null ? ` · ${s.seats_available} left` : "";
  return `${s.date}${time}${seats}`;
}

export function SupplierSlotPickerDialog({
  api,
  itineraryId,
  node,
  overrideUnpaid,
  onBooked,
  onClose,
}: {
  api: Api;
  itineraryId: string;
  node: NodeResponse;
  overrideUnpaid: boolean;
  onBooked: () => Promise<void>;
  onClose: () => void;
}) {
  const currency = node.cost_currency ?? "USD";

  const [slots, setSlots] = useState<SupplierAvailabilityResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notBookable, setNotBookable] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);

  const loadAvailability = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotBookable(false);
    const start = new Date();
    const end = new Date(start.getTime() + AVAILABILITY_WINDOW_DAYS * 24 * 60 * 60 * 1000);
    const result = await supplierAvailability(api, itineraryId, node.id, {
      start: isoDate(start),
      end: isoDate(end),
      currency,
    });
    if (result.ok) {
      setSlots(result.slots);
    } else if (result.detail === "node_not_supplier_bookable") {
      // Supplier booking isn't enabled for this source — offer the manual path.
      setNotBookable(true);
      setSlots([]);
    } else {
      setError(copy(result.detail));
      setSlots([]);
    }
    setLoading(false);
  }, [api, itineraryId, node.id, currency]);

  useEffect(() => {
    void loadAvailability();
  }, [loadAvailability]);

  const selected = useMemo(
    () => (slots ?? []).find((s) => slotKey(s) === selectedKey) ?? null,
    [slots, selectedKey],
  );

  const chooseSlot = (s: SupplierAvailabilityResponse) => {
    setSelectedKey(slotKey(s));
    // Seed one participant in the first category, the rest zero.
    const seeded: Record<string, number> = {};
    (s.prices ?? []).forEach((p, i) => {
      seeded[p.category_id] = i === 0 ? 1 : 0;
    });
    setCounts(seeded);
  };

  const totalCount = useMemo(
    () => Object.values(counts).reduce((sum, c) => sum + c, 0),
    [counts],
  );

  const setCount = (categoryId: string, value: number) => {
    setCounts((prev) => ({ ...prev, [categoryId]: Math.max(0, value) }));
  };

  const finish = useCallback(
    async (result: { ok: boolean; detail?: string }) => {
      if (result.ok) {
        await onBooked();
        onClose();
      } else {
        setError(copy(result.detail ?? "unknown"));
      }
    },
    [onBooked, onClose],
  );

  const reserveAndConfirm = () => {
    if (!selected || totalCount < 1 || busy) return;
    const selection: SupplierSelectionRequest = {
      date: selected.date,
      rate_id: selected.rate_id ?? null,
      start_time_id: selected.start_time_id ?? null,
      currency,
      pricing_categories: (selected.prices ?? [])
        .map((p) => ({ category_id: p.category_id, count: counts[p.category_id] ?? 0 }))
        .filter((pc) => pc.count > 0),
    };
    void (async () => {
      setBusy(true);
      setError(null);
      try {
        await finish(
          await bookNode(api, itineraryId, node.id, {
            override_unpaid: overrideUnpaid,
            supplier_selection: selection,
          }),
        );
      } finally {
        setBusy(false);
      }
    })();
  };

  const bookWithoutSlot = () => {
    if (busy) return;
    void (async () => {
      setBusy(true);
      setError(null);
      try {
        await finish(
          await bookNode(api, itineraryId, node.id, { override_unpaid: overrideUnpaid }),
        );
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-xs"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`Book ${node.title}`}
      data-testid="supplier-slot-dialog"
    >
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col gap-4 overflow-y-auto rounded-lg border border-ink/15 bg-paper p-5 text-ink shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-baseline justify-between gap-2">
          <div className="min-w-0">
            <h4 className="truncate font-serif text-base tracking-tight text-ink">{node.title}</h4>
            <p className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50">
              Choose a slot · {currency}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="supplier-slot-close"
            className="shrink-0 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55 hover:text-ink"
          >
            Close
          </button>
        </header>

        {loading ? (
          <p className="font-sans text-sm text-ink/50">Loading availability…</p>
        ) : notBookable ? (
          <div className="flex flex-col gap-3">
            <p className="font-sans text-sm text-ink/70">
              Live supplier booking isn&apos;t enabled for this item. You can still book it manually
              and record the confirmation # afterwards.
            </p>
            <button
              type="button"
              onClick={bookWithoutSlot}
              disabled={busy}
              data-testid="supplier-book-fallback"
              className="self-start rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Book without a live slot
            </button>
          </div>
        ) : (slots ?? []).length === 0 ? (
          <div className="flex flex-col gap-3">
            <p className="font-sans text-sm italic text-ink/60">
              No availability in the next {AVAILABILITY_WINDOW_DAYS} days.
            </p>
            <button
              type="button"
              onClick={() => void loadAvailability()}
              disabled={busy}
              data-testid="supplier-retry"
              className="self-start rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
            >
              Refresh
            </button>
          </div>
        ) : (
          <>
            <ul
              className="flex max-h-64 flex-col divide-y divide-ink/10 overflow-y-auto rounded-md border border-ink/10"
              data-testid="supplier-slot-list"
            >
              {(slots ?? []).map((s) => {
                const key = slotKey(s);
                const active = key === selectedKey;
                const from = (s.prices ?? [])[0];
                return (
                  <li key={key}>
                    <button
                      type="button"
                      onClick={() => chooseSlot(s)}
                      data-testid={`supplier-slot-${key}`}
                      aria-pressed={active}
                      className={`flex w-full items-baseline justify-between gap-2 px-3 py-2 text-left font-sans text-sm transition-colors ${
                        active ? "bg-ink/5 font-medium text-ink" : "text-ink/80 hover:bg-ink/5"
                      }`}
                    >
                      <span className="min-w-0 truncate">{slotLabel(s)}</span>
                      {from ? (
                        <span className="shrink-0 tabular-nums text-ink/60">
                          from {from.amount} {from.currency}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>

            {selected ? (
              <div className="flex flex-col gap-2" data-testid="supplier-participants">
                <span className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55">
                  Participants
                </span>
                {(selected.prices ?? []).length === 0 ? (
                  <p className="font-sans text-xs italic text-ink/50">
                    No priced categories on this slot.
                  </p>
                ) : (
                  (selected.prices ?? []).map((p) => (
                    <div key={p.category_id} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate font-sans text-sm text-ink/80">
                        Category {p.category_id} · {p.amount} {p.currency}
                      </span>
                      <input
                        type="number"
                        min={0}
                        value={counts[p.category_id] ?? 0}
                        onChange={(e) =>
                          setCount(p.category_id, Number.parseInt(e.target.value, 10) || 0)
                        }
                        data-testid={`supplier-count-${p.category_id}`}
                        className="w-16 rounded-md border border-ink/20 bg-paper-white px-2 py-1 text-right font-sans text-sm tabular-nums text-ink"
                      />
                    </div>
                  ))
                )}
                <button
                  type="button"
                  onClick={reserveAndConfirm}
                  disabled={busy || totalCount < 1}
                  data-testid="supplier-book-confirm"
                  className="mt-1 self-end rounded-md border border-ink/20 bg-paper px-3 py-1.5 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
                >
                  {busy ? "Booking…" : "Reserve & confirm"}
                </button>
              </div>
            ) : null}
          </>
        )}

        {error ? (
          <p role="alert" className="font-sans text-xs font-medium text-[#8b2a1d]">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
