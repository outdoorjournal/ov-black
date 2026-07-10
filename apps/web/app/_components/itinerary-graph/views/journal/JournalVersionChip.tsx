"use client";

// The version chip near the hero (traveler-journal design, phase 4) — the
// Journal's mode indicator + the entry into DIFF MODE:
//
//   · On a FORK: the chip names which version this is ("Your version" for a
//     traveler, "Alternative version" for an advisor — role decides) and
//     carries the *Compare with the trip* toggle. Compare is a toggle over the
//     same Journal DOM, never a route.
//   · On the OFFICIAL trunk when the viewer has an open fork
//     (`viewerOpenForkId`): the chip points at that version and its compare
//     affordance deep-links to the fork's Journal with `?compare=1` — the diff
//     is inherently pairwise and always reads FROM the fork.
//
// `?compare=1` is also how the advisor's reconcile review arrives (the old
// Studio destination routes here), so the toggle seeds itself from the URL
// once on mount.

import { useEffect, useRef } from "react";
import type { Route } from "next";
import Link from "next/link";

import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

export function JournalVersionChip() {
  const { timeline } = useTimelineData();
  const role = itineraryGraphStore.useStore((s) => s.role);
  const viewerOpenForkId = itineraryGraphStore.useStore(
    (s) => s.viewerOpenForkId,
  );
  const diffMode = itineraryGraphStore.useStore((s) => s.diffMode);
  const setDiffMode = itineraryGraphStore.useStore((s) => s.setDiffMode);
  const hasCreds = itineraryGraphStore.useStore((s) =>
    Boolean(s.apiBaseUrl && s.accessToken),
  );

  const isFork = Boolean(timeline.itinerary.forked_from_id);
  const isAdvisor = role === "advisor";

  // Seed compare from the URL exactly once — the reconcile-review deep link
  // (and the trunk chip's own link) land as /dashboard?compare=1.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !isFork) return;
    seeded.current = true;
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("compare") === "1") setDiffMode(true);
  }, [isFork, setDiffMode]);

  if (!hasCreds) return null;

  const chip =
    "inline-flex items-center gap-1.5 rounded-full border border-ink/20 bg-paper/80 px-3 py-1 font-sans text-[11px] font-medium text-ink/80";
  const action =
    "rounded-full border px-3 py-1 font-sans text-[11px] font-medium transition-colors";

  if (isFork) {
    return (
      <div
        data-testid="journal-version-chip"
        className="flex flex-wrap items-center gap-2"
      >
        <span className={chip}>
          <span
            aria-hidden
            className="block h-1.5 w-1.5 rounded-full bg-brand"
          />
          {isAdvisor ? "Alternative version" : "Your version"}
        </span>
        <button
          type="button"
          data-testid="journal-compare-toggle"
          aria-pressed={diffMode}
          onClick={() => setDiffMode(!diffMode)}
          className={`${action} ${
            diffMode
              ? "border-ink bg-ink text-paper hover:opacity-90"
              : "border-ink/20 bg-paper/80 text-ink/80 hover:bg-ink/5"
          }`}
        >
          {diffMode ? "Exit compare" : "Compare with the trip"}
        </button>
      </div>
    );
  }

  // The official trunk, with the viewer's own version open elsewhere.
  if (viewerOpenForkId) {
    return (
      <div
        data-testid="journal-version-chip"
        className="flex flex-wrap items-center gap-2"
      >
        <Link
          href={`/itinerary/${viewerOpenForkId}/dashboard` as Route}
          data-testid="journal-version-open-fork"
          className={`${chip} transition-colors hover:bg-ink/5`}
        >
          <span
            aria-hidden
            className="block h-1.5 w-1.5 rounded-full bg-brand"
          />
          {isAdvisor ? "An alternative version exists" : "Your version"} →
        </Link>
        <Link
          href={
            `/itinerary/${viewerOpenForkId}/dashboard?compare=1` as Route
          }
          data-testid="journal-compare-link"
          className={`${action} border-ink/20 bg-paper/80 text-ink/80 hover:bg-ink/5`}
        >
          Compare with the trip
        </Link>
      </div>
    );
  }

  return null;
}
