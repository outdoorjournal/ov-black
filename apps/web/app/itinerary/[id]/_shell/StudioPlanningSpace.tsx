"use client";

// The advisor Studio destination — now Diff-only (M006). Since the harmonization,
// the Build authoring tools live on the Timeline toolbar (the unified Add composer
// + the Analyze modal), so Studio's sole remaining job is reconciling an
// alternative version against its baseline. The route is advisor-gated server-side
// and its rail item only shows for alternatives, so a non-alternative reaching here
// (a stale direct link) gets a quiet empty state rather than an empty panel.

import { DiffPanel } from "@/app/_components/itinerary-graph/views/horizontal/DiffPanel";
import {
  itineraryGraphStore,
  selectEditable,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

export function StudioPlanningSpace() {
  const { timeline } = useTimelineData();
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const editable = itineraryGraphStore.useStore(selectEditable);

  const forkedFromId = timeline.itinerary.forked_from_id ?? null;

  if (!forkedFromId) {
    return (
      <div
        data-testid="studio"
        className="flex min-h-0 flex-1 items-center justify-center px-6 py-10"
      >
        <p className="max-w-sm text-center font-serif text-[15px] italic leading-relaxed text-ink/55">
          Nothing to reconcile — this is the agreed plan. Reconcile becomes
          available on an alternative version.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="studio" className="flex min-h-0 flex-1 flex-col">
      <DiffPanel
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        forkItineraryId={itineraryId}
        baselineItineraryId={forkedFromId}
        editable={editable}
      />
    </div>
  );
}
