"use client";

// The advisor Studio destination (M006/PS1, transitional). The eight-tab aside
// split three ways: chat → the concierge column, Party/Vault/Invoices/Booking →
// (eventually) the Dashboard (PS3), and Build/Diff → this advisor-only inspector
// (PS6 makes it the final home). For PS1 the not-yet-rehomed panels all live here
// so nothing is lost. The route is advisor-gated server-side; this reads the
// shared store, so the lock acquired on the Timeline carries over.

import { useState } from "react";

import { AuthoringPanel } from "@/app/_components/itinerary-graph/views/horizontal/AuthoringPanel";
import { BookingPanel } from "@/app/_components/itinerary-graph/views/horizontal/BookingPanel";
import { DiffPanel } from "@/app/_components/itinerary-graph/views/horizontal/DiffPanel";
import { InvoicePanel } from "@/app/_components/itinerary-graph/views/horizontal/InvoicePanel";
import { PartyPanel } from "@/app/_components/itinerary-graph/views/horizontal/PartyPanel";
import { VaultPanel } from "@/app/_components/itinerary-graph/views/horizontal/VaultPanel";
import {
  itineraryGraphStore,
  selectEditable,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

type StudioTab = "build" | "diff" | "party" | "vault" | "invoices" | "booking";

export function StudioPlanningSpace() {
  const { timeline } = useTimelineData();
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const editable = itineraryGraphStore.useStore(selectEditable);

  const forkedFromId = timeline.itinerary.forked_from_id ?? null;
  const isAlternative = Boolean(forkedFromId);
  const clientId = timeline.itinerary.client_id;

  const tabs: StudioTab[] = [
    "build",
    ...(isAlternative ? (["diff"] as const) : []),
    "party",
    "vault",
    "invoices",
    "booking",
  ];
  const [tab, setTab] = useState<StudioTab>(isAlternative ? "diff" : "build");

  return (
    <div data-testid="studio" className="flex min-h-0 flex-1 flex-col">
      <div
        data-testid="studio-tabs"
        role="tablist"
        className="flex shrink-0 flex-wrap gap-1 border-b border-ink/10 bg-paper/85 px-3 py-2 backdrop-blur-sm"
      >
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            data-testid={`studio-tab-${t}`}
            className={`h-8 rounded-md px-3 font-sans text-[11px] uppercase tracking-[0.16em] transition-colors ${
              tab === t ? "bg-ink/10 text-ink" : "text-ink/55 hover:bg-ink/5"
            }`}
          >
            {STUDIO_TAB_LABEL[t]}
          </button>
        ))}
      </div>

      <div className="relative min-h-0 flex-1">
        <div className={tab === "build" ? "h-full" : "hidden"}>
          <AuthoringPanel
            tzOffsetHours={timeline.timezoneOffsetHours}
            days={timeline.days}
          />
        </div>
        {isAlternative && forkedFromId ? (
          <div className={tab === "diff" ? "h-full" : "hidden"}>
            <DiffPanel
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              forkItineraryId={itineraryId}
              baselineItineraryId={forkedFromId}
              editable={editable}
            />
          </div>
        ) : null}
        <div className={tab === "party" ? "h-full" : "hidden"}>
          <PartyPanel
            clientId={clientId}
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
          />
        </div>
        <div className={tab === "vault" ? "h-full" : "hidden"}>
          <VaultPanel
            clientId={clientId}
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
          />
        </div>
        <div className={tab === "invoices" ? "h-full" : "hidden"}>
          <InvoicePanel
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
            editable={editable}
          />
        </div>
        <div className={tab === "booking" ? "h-full" : "hidden"}>
          <BookingPanel
            itineraryId={itineraryId}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
            editable={editable}
          />
        </div>
      </div>
    </div>
  );
}

const STUDIO_TAB_LABEL: Record<StudioTab, string> = {
  build: "Build",
  diff: "Diff",
  party: "Party",
  vault: "Vault",
  invoices: "Invoices",
  booking: "Booking",
};
