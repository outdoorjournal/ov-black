"use client";

// The advisor Studio destination. Since M006 this was Diff-only (reconciling
// an alternative against its baseline); with the Journal's diff mode (phase 4)
// the RECONCILE REVIEW lives in the Journal itself — the unified fork-vs-trunk
// compare with per-change accept/keep in the rail — so this destination now
// routes there (`/dashboard?compare=1` seeds the toggle). The full DiffPanel
// survives on the Timeline's Diff tab for the feasibility-check + override
// escape hatch; a non-alternative reaching here (a stale direct link) still
// gets the quiet empty state.

import { useEffect } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

export function StudioPlanningSpace() {
  const { timeline } = useTimelineData();
  const router = useRouter();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);

  const forkedFromId = timeline.itinerary.forked_from_id ?? null;

  useEffect(() => {
    if (!forkedFromId) return;
    router.replace(`/itinerary/${itineraryId}/dashboard?compare=1` as Route);
  }, [forkedFromId, itineraryId, router]);

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
    <div
      data-testid="studio"
      className="flex min-h-0 flex-1 items-center justify-center px-6 py-10"
    >
      <p className="max-w-sm text-center font-serif text-[15px] italic leading-relaxed text-ink/55">
        Opening the review in the Journal…
      </p>
    </div>
  );
}
