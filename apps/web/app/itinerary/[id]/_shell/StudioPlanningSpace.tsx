"use client";

// The advisor Studio destination (M006). The eight-tab aside split three ways:
// chat → the concierge column, Party/Vault/Invoices/Booking → the per-trip
// Dashboard (PS3, now their home), and Build/Diff → this advisor-only authoring
// inspector. The route is advisor-gated server-side; this reads the shared store,
// so the lock acquired on the Timeline carries over. PS6 finalises Studio and
// tears down the last in-canvas aside.

import { useState } from "react";

import { AuthoringPanel } from "@/app/_components/itinerary-graph/views/horizontal/AuthoringPanel";
import { DiffPanel } from "@/app/_components/itinerary-graph/views/horizontal/DiffPanel";
import {
  itineraryGraphStore,
  selectEditable,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

type StudioTab = "build" | "diff";

export function StudioPlanningSpace() {
  const { timeline } = useTimelineData();
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const editable = itineraryGraphStore.useStore(selectEditable);

  const forkedFromId = timeline.itinerary.forked_from_id ?? null;
  const isAlternative = Boolean(forkedFromId);

  const tabs: StudioTab[] = ["build", ...(isAlternative ? (["diff"] as const) : [])];
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
      </div>
    </div>
  );
}

const STUDIO_TAB_LABEL: Record<StudioTab, string> = {
  build: "Build",
  diff: "Diff",
};
