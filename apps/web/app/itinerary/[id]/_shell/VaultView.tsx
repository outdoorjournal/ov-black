"use client";

// The Vault destination — the trip's travel documents (passports, visas, etc.)
// as a first-class Rail surface, rehomed from the old dashboard footer. Advisor-
// focused (the Rail only offers this noun to advisors); reads the shared shell
// store like the other routed views. The clientId the VaultPanel needs comes off
// the timeline context the layout provides.

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

import { VaultPanel } from "@/app/_components/itinerary-graph/views/horizontal/VaultPanel";

export function VaultView() {
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const { timeline } = useTimelineData();
  const clientId = timeline.itinerary.client_id ?? null;

  if (!itineraryId) {
    return (
      <p className="mx-auto max-w-3xl px-4 py-10 font-sans text-sm text-ink/50">
        Loading…
      </p>
    );
  }

  // Own the scroll like the other routed destinations: the shell's <main> is a
  // fixed-height flex column with overflow-hidden, so the view must be the
  // scroll container itself (min-h-0 + overflow-y-auto) or its content is clipped.
  return (
    <div
      data-testid="vault-view"
      className="min-h-0 flex-1 overflow-y-auto bg-paper"
    >
      <div className="mx-auto w-full max-w-3xl px-4 py-6">
        <VaultPanel
          clientId={clientId}
          itineraryId={itineraryId}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
        />
      </div>
    </div>
  );
}
