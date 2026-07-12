"use client";

// The per-trip Finances destination (doc/thoughts.md) — the advisor's billing
// cockpit as a Rail surface. Leads with the per-item cost table (every priced
// item: invoiced / paid / remaining / deposit due), then the invoice cards +
// issuance actions below. Reads the shared shell store like the other routed
// views. Invoicing is advisor-only server-side and independent of the graph
// edit-lock — it must work on an approved trip — so it gates on ROLE; a traveler
// who reaches it sees everything read-only.

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import { FinancesTable } from "@/app/_components/itinerary-graph/views/horizontal/FinancesTable";
import { InvoicePanel } from "@/app/_components/itinerary-graph/views/horizontal/InvoicePanel";

export function FinancesView() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  if (!itineraryId) {
    return (
      <p className="mx-auto max-w-3xl px-4 py-10 font-sans text-sm text-ink/50">Loading…</p>
    );
  }

  // Own the scroll like DashboardView: the shell's <main> is a fixed-height flex
  // column with `overflow-hidden`, so the routed destination must be the scroll
  // container itself (min-h-0 + overflow-y-auto) or its content is clipped.
  return (
    <div data-testid="finances-view" className="min-h-0 flex-1 overflow-y-auto bg-paper">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
        <FinancesTable
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
        />
        <InvoicePanel
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
          canManage={role === "advisor"}
        />
      </div>
    </div>
  );
}
