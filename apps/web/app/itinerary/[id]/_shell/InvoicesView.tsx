"use client";

// The Invoices destination (ADV-11) — the advisor's billing CRUD for this
// itinerary as a first-class Rail surface (a full page beats a modal for managing
// several invoices + their line items). Reads the shared shell store like the
// other routed views. Invoicing is advisor-only server-side and independent of
// the graph edit-lock — it must work on an approved trip — so it gates on ROLE,
// not `selectEditable`; a traveler who reaches it sees invoices read-only.

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import { InvoicePanel } from "@/app/_components/itinerary-graph/views/horizontal/InvoicePanel";

export function InvoicesView() {
  const role = itineraryGraphStore.useStore((s) => s.role);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  if (!itineraryId) {
    return (
      <p className="mx-auto max-w-3xl px-4 py-10 font-sans text-sm text-ink/50">
        Loading…
      </p>
    );
  }

  return (
    <div
      data-testid="invoices-view"
      className="mx-auto w-full max-w-3xl px-4 py-6"
    >
      <InvoicePanel
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        canManage={role === "advisor"}
      />
    </div>
  );
}
