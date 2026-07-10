"use client";

// The Journal — the traveler's narrative reading of the itinerary graph
// (traveler-journal design, phase 1). Event-proportional, not time-
// proportional: a spine of cards grouped by day, gaps bucketed (plain segment /
// quiet moment / night / elision), with a right rail that reacts to whatever
// moment the reader is looking at. Read-only in this phase; one Journal for
// every role (advisors land here too — Studio stays the workbench).
//
// Same screen, responsive: below lg the rail column disappears, the Journal
// goes full-width, and activating a card deep-links to /item/[nodeId] (the
// existing full-detail destination) instead of driving the rail.

import { useCallback, useMemo, type ReactNode, type RefObject } from "react";
import { useRouter } from "next/navigation";

import type { NodeResponse } from "../../model/types";
import { attachedNotesByHost } from "../../shared/attachedNotes";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";
import { datesPinned } from "../../model/time";

import { DayHeader } from "./DayHeader";
import { JournalAltGroup, JournalNode } from "./JournalNode";
import { RightRail } from "./RightRail";
import { NightSegment, SPINE_COL_PX } from "./Spine";
import { toJournal, type JournalDaySection } from "./toJournal";
import { useScrollActive } from "./useScrollActive";
import { ElisionMarker, GapSegment, VirtualNode } from "./VirtualNode";

export function JournalView({
  scrollRootRef,
  railIdle,
}: {
  /** The scrolling ancestor (the dashboard's scroll container) — the
   *  scroll-active center band is measured against it. */
  scrollRootRef?: RefObject<HTMLElement | null> | undefined;
  /** The rail's resting-state content (next action · approve-all · balance),
   *  composed by the dashboard so the Journal stays presentation-only. */
  railIdle: ReactNode;
}) {
  const router = useRouter();
  const { timeline } = useTimelineData();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const edges = itineraryGraphStore.useStore((s) => s.edges);
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusNode = itineraryGraphStore.useStore((s) => s.focusNode);
  const awaitingProposal = itineraryGraphStore.useStore((s) => s.awaitingProposal);

  const tz = timeline.timezoneOffsetHours;
  const journal = useMemo(
    () =>
      toJournal({
        nodes,
        edges,
        days: timeline.days,
        timezoneOffsetHours: tz,
      }),
    [nodes, edges, timeline.days, tz],
  );
  const attachedNotes = useMemo(() => attachedNotesByHost(nodes), [nodes]);
  const pinned = datesPinned(timeline.itinerary);

  const observe = useScrollActive({ scrollRootRef });

  // A click pins the node (the rail follows). Below lg there is no rail on
  // screen, so the same gesture deep-links to the full detail destination —
  // one screen, responsive; never a parallel route.
  const onActivate = useCallback(
    (nodeId: string) => {
      focusNode(nodeId, "click");
      const desktop =
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(min-width: 1024px)").matches;
      if (!desktop) {
        router.push(`/itinerary/${itineraryId}/item/${nodeId}`);
      }
    },
    [focusNode, router, itineraryId],
  );

  return (
    <div
      data-testid="journal"
      className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 sm:px-6 lg:flex-row lg:gap-10"
    >
      {/* The Journal column */}
      <div className="min-w-0 flex-1 lg:order-1">
        {journal.nodeCount === 0 ? (
          <EmptyJournal awaitingProposal={awaitingProposal} />
        ) : (
          <div className="flex flex-col gap-2">
            {journal.sections.map((section) =>
              section.kind === "elision" ? (
                <ElisionMarker
                  key={`elide-${section.startDate}`}
                  elision={section}
                />
              ) : (
                <DaySection
                  key={section.date}
                  section={section}
                  tz={tz}
                  pinned={pinned}
                  focusedNodeId={focusedNodeId}
                  attachedNotes={attachedNotes}
                  onActivate={onActivate}
                  observe={observe}
                />
              ),
            )}
            <p className="mt-6 pl-[var(--spine-col)] font-serif text-[12px] italic text-ink/35" style={spineColStyle}>
              — the end of the journey —
            </p>
          </div>
        )}
      </div>

      {/* The right rail — fixed beside the story on desktop. Below lg it
          collapses to the idle glance above the Journal (node detail
          deep-links to /item/[nodeId] instead) — same screen, responsive. */}
      <aside
        data-testid="journal-rail"
        className="w-full lg:order-2 lg:w-[340px] lg:shrink-0"
      >
        <div className="lg:sticky lg:top-4">
          <RightRail idle={railIdle} />
        </div>
      </aside>
    </div>
  );
}

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

function DaySection({
  section,
  tz,
  pinned,
  focusedNodeId,
  attachedNotes,
  onActivate,
  observe,
}: {
  section: JournalDaySection;
  tz: number;
  pinned: boolean;
  focusedNodeId: string | null;
  attachedNotes: Map<string, NodeResponse[]>;
  onActivate: (nodeId: string) => void;
  observe: ReturnType<typeof useScrollActive>;
}) {
  return (
    <section data-testid="journal-day" data-date={section.date}>
      <DayHeader label={section.label} date={section.date} datesPinned={pinned} />
      <div className="relative flex flex-col gap-2 py-3" style={spineColStyle}>
        {/* The continuous spine — one line the circles sit on. */}
        <span
          aria-hidden
          className="absolute bottom-0 top-0 w-px bg-ink/15"
          style={{ left: SPINE_COL_PX / 2 }}
        />
        {section.entries.map((entry, i) => {
          switch (entry.kind) {
            case "node":
              return (
                <JournalNode
                  key={entry.node.id}
                  node={entry.node}
                  tzOffsetHours={tz}
                  active={focusedNodeId === entry.node.id}
                  attachedNoteCount={
                    attachedNotes.get(entry.node.id)?.length ?? 0
                  }
                  onActivate={onActivate}
                  observeRef={observe(entry.node.id)}
                />
              );
            case "alt":
              return (
                <JournalAltGroup
                  key={`alt-${entry.groupKey}`}
                  nodes={entry.nodes}
                  tzOffsetHours={tz}
                  focusedNodeId={focusedNodeId}
                  attachedNotes={attachedNotes}
                  onActivate={onActivate}
                  observeRef={observe}
                />
              );
            case "gap":
              return (
                <GapSegment key={`gap-${section.date}-${i}`} minutes={entry.minutes} />
              );
            case "quiet":
              return (
                <VirtualNode
                  key={entry.id}
                  caption={entry.caption}
                  minutes={entry.minutes}
                />
              );
          }
        })}
        {section.night ? (
          <NightSegment title={section.night.node?.title} />
        ) : null}
      </div>
    </section>
  );
}

function EmptyJournal({ awaitingProposal }: { awaitingProposal: boolean }) {
  return (
    <div
      data-testid="journal-empty"
      className="rounded-lg border border-dashed border-ink/15 px-6 py-14 text-center"
    >
      <p className="font-serif text-lg italic text-ink/55">
        {awaitingProposal
          ? "Your journey is being crafted — the first pages arrive soon."
          : "The journal is blank — the story starts with the first card."}
      </p>
    </div>
  );
}
