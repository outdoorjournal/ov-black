"use client";

// The Journal's right rail — the page's reactive margin. Two states:
//   idle    nothing activated yet → the trip at a glance (next action,
//           approve-all, balance — composed by the dashboard and passed in).
//   active  a node is scroll-active or click-pinned → its detail, reusing the
//           same NodeZoomCard the /item/[nodeId] destination renders, plus a
//           deep link to that full detail surface.
//
// Same screen, responsive: the detail state is desktop-only (below lg a card
// tap deep-links to /item/[nodeId] instead), so the idle glance renders ONCE
// and simply stays visible on small screens even while a node is active.

import type { Route } from "next";
import Link from "next/link";

import { NodeZoomCard } from "../../shared/cards/NodeZoomCard";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

export function RightRail({ idle }: { idle: React.ReactNode }) {
  const { timeline } = useTimelineData();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusSource = itineraryGraphStore.useStore((s) => s.focusSource);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);

  // Only a real Journal interaction (scroll or click) flips the rail to the
  // node detail — the store's seeded default focus keeps the idle glance.
  const active =
    focusSource !== null && focusedNodeId
      ? (nodes.find((n) => n.id === focusedNodeId) ?? null)
      : null;

  return (
    <>
      <div
        data-testid="journal-rail-idle"
        className={[
          "flex-col gap-4",
          active ? "flex lg:hidden" : "flex",
        ].join(" ")}
      >
        {idle}
      </div>
      {active ? (
        <div
          data-testid="journal-rail-detail"
          className="hidden flex-col gap-3 lg:flex"
        >
          <NodeZoomCard
            node={active}
            tzOffsetHours={timeline.timezoneOffsetHours}
          />
          <Link
            href={`/itinerary/${itineraryId}/item/${active.id}` as Route}
            data-testid="journal-rail-open-detail"
            className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
          >
            Open full detail →
          </Link>
        </div>
      ) : null}
    </>
  );
}
