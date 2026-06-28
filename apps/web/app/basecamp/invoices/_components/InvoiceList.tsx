import Link from "next/link";

import type { MyInvoiceSummary } from "@ov-black/api-client";

// Traveler cross-trip invoice listing (/basecamp/invoices). Presentational —
// each row links to the existing /invoices/{id} pay page. Mirrors the vault's
// DocumentList styling: craft-clean, no emoji, paper-on-dark status pills.

const STATUS_BADGE: Record<MyInvoiceSummary["status"], string> = {
  draft: "border-paper/25 text-paper/55",
  issued: "border-sky-300/40 text-sky-200/90",
  paid: "border-emerald-300/40 text-emerald-200/90",
  void: "border-paper/15 text-paper/35 line-through",
};

function StatusBadge({ status }: { status: MyInvoiceSummary["status"] }) {
  return (
    <span
      data-testid={`invoice-status-${status}`}
      className={`shrink-0 rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] ${STATUS_BADGE[status]}`}
    >
      {status}
    </span>
  );
}

export function InvoiceList({ invoices }: { invoices: MyInvoiceSummary[] }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 pb-16 pt-2 sm:px-10">
      <header className="flex flex-col gap-3 border-b border-paper/10 pb-6">
        <Link
          href="/basecamp"
          className="font-sans text-[10px] uppercase tracking-[0.4em] text-paper/55 transition-colors hover:text-paper"
        >
          ← Basecamp
        </Link>
        <h1 className="font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Your invoices
        </h1>
        <p className="max-w-xl font-sans text-sm leading-relaxed text-paper/70">
          Deposits and balances across your journeys. Open any issued invoice to
          settle it securely; paid invoices keep their receipt.
        </p>
      </header>

      {invoices.length === 0 ? (
        <p className="font-sans text-sm italic text-paper/45">No invoices yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {invoices.map((inv) => (
            <li key={inv.id}>
              <Link
                href={`/invoices/${inv.id}`}
                data-testid={`invoice-row-${inv.id}`}
                className="group flex items-start justify-between gap-4 rounded-sm border border-paper/10 bg-paper/[0.04] px-4 py-3 transition-colors hover:bg-paper/[0.07]"
              >
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="truncate font-serif text-paper">
                    {inv.label || "Invoice"}
                  </span>
                  <span className="truncate font-sans text-xs text-paper/55">
                    {inv.itinerary_title}
                  </span>
                  {inv.due_at ? (
                    <span className="font-sans text-[11px] text-paper/45">
                      Due {inv.due_at}
                    </span>
                  ) : null}
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1">
                  <StatusBadge status={inv.status} />
                  <span className="font-sans text-sm tabular-nums text-paper/80">
                    {inv.total} {inv.currency}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
