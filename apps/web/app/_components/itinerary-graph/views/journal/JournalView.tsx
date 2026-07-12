"use client";

// The Journal — the traveler's narrative reading of the itinerary graph
// (traveler-journal design). Event-proportional, not time-proportional: a
// spine of cards grouped by day, gaps bucketed (plain segment / quiet moment /
// night / elision), with a right rail that reacts to whatever moment the
// reader is looking at. One Journal for every role (advisors land here too —
// Studio stays the workbench). Phase 2 opened the margin channel; phase 3 adds
// interaction depth:
//
//   · drag-to-move along the spine (editable fork) — drop slots are the GAPS
//     between cards; a drop assigns a sensible slot time (no time-pixel math).
//     On the official trunk the same gesture OFFERS the lazy-fork path
//     ("make this yours?") instead of silently failing.
//   · insert on the line — the `+` grows into the Collection-first picker on
//     an editable fork (see AddNoteOnLine).
//   · alternatives render as the spine splitting (JournalAltGroup) and
//     problems as red-ring/⚠/caption (problems.ts), explained in the rail.
//
// Phase 4 adds DIFF MODE — a toggle over this same DOM (never a route): the
// unified fork-vs-trunk compare (toJournalDiff) rendered as tracked changes on
// ONE spine — stitches, dots, moved chips, and ghost rows for trunk-only
// nodes; a slim dashed second thread runs beside the spine through diverged
// days as a region cue. The spine never splits for a version diff (splits are
// the alternatives vocabulary). Diff mode is a reading/deciding mode: content
// gestures (drag, insert, in-place edit) sit out; notes stay open.
//
// Phase 5 adds ATMOSPHERE & SCALE: the ambient layer behind the paper (mounted
// by the dashboard host), the floating day rail + more-below tail cue, elision
// polish, windowed rendering on the card rows, and CINEMA MODE — a second mode
// flag over this same DOM (mutually exclusive with diff mode; the store
// enforces it) where the chrome fades and a rAF driver plays the journey.
//
// Same screen, responsive: below lg the rail column disappears, the Journal
// goes full-width, and activating a card deep-links to /item/[nodeId] (the
// existing full-detail destination) instead of driving the rail.

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { useRouter } from "next/navigation";

import type { NodeResponse } from "../../model/types";
import { subgraphChildrenByParent } from "../../shared/subgraph";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";
import { datesPinned } from "../../model/time";
import { NodeCard } from "../horizontal/NodeCard";

import { CinemaDriver } from "./Cinema";
import { DayHeader } from "./DayHeader";
import { DayRail } from "./DayRail";
import {
  cardBoundsOf,
  dropSlotMinutes,
  journalDropMode,
  journalSlotId,
  minuteLabel,
  nodeIdFromJournalDragId,
  SLOT_EMPTY_DAY_MIN,
} from "./journalEditing";
import { JournalAltGroup, JournalGhostNode, JournalNode } from "./JournalNode";
import { useConciergeControl } from "@/app/itinerary/[id]/_shell/ConciergeControl";

import { AddNoteOnLine } from "./JournalNotes";
import { JournalZoomControls } from "./JournalZoomControls";
import { MoreBelowCue } from "./MoreBelow";
import { journalProblems, type JournalProblem } from "./problems";
import { RightRail } from "./RightRail";
import { useIs2xl } from "./useIs2xl";
import { CardDetailView } from "@/app/itinerary/[id]/_shell/CardDetailView";
import { JOURNEY_INDENT_PX, NightSegment, SPINE_COL_PX } from "./Spine";
import { toJournal, type JournalDaySection } from "./toJournal";
import {
  isGhostId,
  toJournalDiff,
  type JournalDiffView,
  type JournalNodeDiff,
} from "./toJournalDiff";

type JournalDiffViewOrNull = JournalDiffView | null;
import { useScrollActive } from "./useScrollActive";
import { ElisionMarker, GapSegment, VirtualNode } from "./VirtualNode";

/** The trunk drag that's waiting on "make this yours?" (the fork offer). */
type ForkOffer = {
  nodeId: string;
  dayKey: string;
  minute: number;
  title: string;
};

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
  const findings = itineraryGraphStore.useStore((s) => s.findings);
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusSource = itineraryGraphStore.useStore((s) => s.focusSource);
  const focusNode = itineraryGraphStore.useStore((s) => s.focusNode);
  const awaitingProposal = itineraryGraphStore.useStore((s) => s.awaitingProposal);
  const viewerOpenForkId = itineraryGraphStore.useStore((s) => s.viewerOpenForkId);
  const role = itineraryGraphStore.useStore((s) => s.role);
  const diffMode = itineraryGraphStore.useStore((s) => s.diffMode);
  const diff = itineraryGraphStore.useStore((s) => s.diff);
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  // What a spine drop DOES here — role (via the selectors) is the source of
  // truth: move on an editable fork, lazy-fork on the draft preview, offer the
  // fork on the trunk, nothing at all otherwise (no drag affordance).
  const dropMode = itineraryGraphStore.useStore(journalDropMode);
  const storeApi = itineraryGraphStore.useStoreApi();
  // The very-large tier (≥1536): the right region promotes from the cockpit
  // rail to the full detail inline — selection IS the open, no modal, no second
  // click (rail redesign, phase 4). Diff mode stays on the cockpit (its
  // accept/keep decisions live there), so inline-detail is normal-reading only.
  const is2xl = useIs2xl();

  const tz = timeline.timezoneOffsetHours;
  // Diff mode is only meaningful on a fork (compare is inherently pairwise:
  // this version against its baseline). The gesture gates flip as soon as the
  // toggle is on; the annotated sequence lands when the diff response does.
  const diffActive = diffMode && Boolean(timeline.itinerary.forked_from_id);
  const inlineDetail = is2xl && !diffActive;
  // Only a real interaction (scroll/click) drives the inline detail — the
  // store's seeded default focus keeps the idle glance until the reader moves.
  // A diff-mode ghost (trunk-only, synthesized) has no detail page, so it never
  // opens the inline detail.
  const inlineDetailNodeId =
    inlineDetail &&
    focusSource !== null &&
    focusedNodeId &&
    !isGhostId(focusedNodeId)
      ? focusedNodeId
      : null;
  // Expand-to-lock (2xl): the region defaults to the cheap cockpit (follows the
  // scroll-active card); "Open full" EXPANDS the full detail in place and hard-
  // locks focus so scrolling can't swap it, until dismissed. A change of active
  // card (clicking another, or the detail clearing) drops the expansion + lock.
  const [inlineExpanded, setInlineExpanded] = useState(false);
  useEffect(() => {
    setInlineExpanded(false);
    storeApi.getState().setFocusLocked(false);
  }, [inlineDetailNodeId, storeApi]);
  const expandInlineDetail = useCallback(() => {
    setInlineExpanded(true);
    storeApi.getState().setFocusLocked(true);
  }, [storeApi]);
  const collapseInlineDetail = useCallback(() => {
    setInlineExpanded(false);
    storeApi.getState().setFocusLocked(false);
  }, [storeApi]);
  const showInlineFull = Boolean(inlineDetailNodeId) && inlineExpanded;
  const toggleInlineDetail = useCallback(() => {
    if (inlineExpanded) collapseInlineDetail();
    else expandInlineDetail();
  }, [inlineExpanded, expandInlineDetail, collapseInlineDetail]);
  const diffView = useMemo<JournalDiffViewOrNull>(() => {
    if (!diffActive) return null;
    const base = {
      nodes,
      edges,
      days: timeline.days,
      timezoneOffsetHours: tz,
    };
    if (diff) return toJournalDiff({ ...base, diff });
    // Toggled on, response not landed yet — the compare register (and the
    // gesture gates) apply immediately; the annotations arrive with the diff.
    return {
      journal: toJournal(base),
      annotations: new Map(),
      ghosts: new Map(),
      divergedDays: new Set<string>(),
      counts: { added: 0, removed: 0, changed: 0, moved: 0 },
      total: 0,
      summary: "",
    };
  }, [diffActive, diff, nodes, edges, timeline.days, tz]);
  const journal = useMemo(
    () =>
      diffView?.journal ??
      toJournal({
        nodes,
        edges,
        days: timeline.days,
        timezoneOffsetHours: tz,
      }),
    [diffView, nodes, edges, timeline.days, tz],
  );
  // Embedded subgraphs (a multi-day card's internal journey), parent → days.
  const subgraphChildren = useMemo(
    () => subgraphChildrenByParent(nodes),
    [nodes],
  );
  // Problem states — driven by whatever problem data exists client-side today
  // (Analyze findings + the typed metadata.problem socket); see problems.ts.
  const problems = useMemo(
    () => journalProblems(nodes, findings),
    [nodes, findings],
  );
  // Which sections carry a packaged journey (the parent card's day or a day
  // holding one of its derived beats). Adjacency decides where the journey
  // thread BRIDGES a day boundary, so the marker runs unbroken from the parent
  // card to the last beat — through night treatments, day rules, and the gaps
  // between sections — instead of restarting each day.
  const journeyDays = useMemo(
    () =>
      journal.sections.map(
        (s) =>
          s.kind === "day" &&
          s.entries.some(
            (e) =>
              e.kind === "node" &&
              (e.journey !== undefined ||
                (subgraphChildren.get(e.node.id)?.length ?? 0) > 0),
          ),
      ),
    [journal, subgraphChildren],
  );
  const pinned = datesPinned(timeline.itinerary);

  const observe = useScrollActive({ scrollRootRef });

  // ── Drag-to-move along the spine ────────────────────────────────────────────
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );
  // Stable id so @dnd-kit's DndDescribedBy counter matches across SSR/hydration
  // (else React logs an aria-describedby hydration mismatch on every draggable).
  const dndContextId = useId();
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [forkOffer, setForkOffer] = useState<ForkOffer | null>(null);
  // Diff mode is a reading/deciding mode — the content gestures sit out.
  // Cinema is pure reading; gestures sit out there too.
  const dragEnabled = !diffActive && !cinemaMode && dropMode !== "none";

  const activeDragNode = useMemo(
    () =>
      activeDragId ? (nodes.find((n) => n.id === activeDragId) ?? null) : null,
    [activeDragId, nodes],
  );

  const onDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveDragId(null);
      const over = event.over;
      if (!over) return;
      const data = over.data.current as
        | { dayKey?: unknown; minute?: unknown }
        | undefined;
      if (
        !data ||
        typeof data.dayKey !== "string" ||
        typeof data.minute !== "number"
      ) {
        return;
      }
      const nodeId = nodeIdFromJournalDragId(String(event.active.id));
      const st = storeApi.getState();
      switch (journalDropMode(st)) {
        case "move":
          st.moveNode(nodeId, data.dayKey, data.minute);
          break;
        case "fork-and-move":
          // Draft-mine preview: the FIRST edit lazily forks and carries the
          // move onto the new fork (the store's existing path).
          st.forkAndMove(nodeId, data.dayKey, data.minute, (id) =>
            router.push(`/itinerary/${id}`),
          );
          break;
        case "offer-fork": {
          // The official trunk: don't mutate — offer the working-copy path.
          const node = st.nodes.find((n) => n.id === nodeId);
          setForkOffer({
            nodeId,
            dayKey: data.dayKey,
            minute: data.minute,
            title: node?.title ?? "this card",
          });
          break;
        }
        case "none":
          break;
      }
    },
    [storeApi, router],
  );

  const confirmForkOffer = useCallback(() => {
    const offer = forkOffer;
    if (!offer) return;
    setForkOffer(null);
    const st = storeApi.getState();
    // An open fork already exists → continue there (the existing version-
    // switch path); otherwise enter draft-mine and lazy-fork WITH the move.
    if (st.viewerOpenForkId) {
      router.push(`/itinerary/${st.viewerOpenForkId}`);
      return;
    }
    st.selectVersion("mine", () => {});
    storeApi
      .getState()
      .forkAndMove(offer.nodeId, offer.dayKey, offer.minute, (id) =>
        router.push(`/itinerary/${id}`),
      );
  }, [forkOffer, storeApi, router]);

  // A click pins the node (the rail follows). Below lg there is no rail on
  // screen, so the same gesture deep-links to the full detail destination —
  // one screen, responsive; never a parallel route.
  const onActivate = useCallback(
    (nodeId: string) => {
      focusNode(nodeId, "click");
      // A diff-mode GHOST is synthesized (trunk-only) — there is no
      // /item/[nodeId] destination for it, so it only drives the rail.
      if (isGhostId(nodeId)) return;
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
    <DndContext
      id={dndContextId}
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={(e) =>
        setActiveDragId(nodeIdFromJournalDragId(String(e.active.id)))
      }
      onDragEnd={onDragEnd}
      onDragCancel={() => setActiveDragId(null)}
    >
      <div
        data-testid="journal"
        className="flex w-full flex-col gap-8 px-4 py-8 sm:px-6 lg:flex-row lg:gap-10"
      >
        {/* The floating day minimap — an in-flow sticky column immediately left
            of the Journal spine on desktop (its mobile bottom pill is fixed).
            Rendered here rather than as a viewport-fixed sibling so it hugs the
            timeline and never overlaps the left nav / concierge column. */}
        <DayRail
          journal={journal}
          totalDays={timeline.days.length}
          divergedDays={diffView?.divergedDays ?? null}
          scrollRootRef={scrollRootRef}
        />

        {/* The Journal column — left-anchored (the container no longer centers)
            and capped at a reading measure so the spine rides the left instead
            of stretching; the freed width trails right for the rail / the 2xl
            inline-detail tier. */}
        <div className="min-w-0 flex-1 lg:order-2 lg:max-w-[680px]">
          {journal.nodeCount === 0 && awaitingProposal ? (
            <EmptyJournal awaitingProposal={awaitingProposal} />
          ) : (
            <div className="flex flex-col gap-2">
              {/* The timeline-scale dial — breathe the duration bars + gaps in
                  and out. Only meaningful once there's a story to scale; sits
                  out of diff mode (a reading/deciding pass). */}
              {journal.nodeCount > 0 && !diffActive ? (
                <div className="mb-1 flex justify-end pl-[var(--spine-col)]" style={spineColStyle}>
                  <JournalZoomControls />
                </div>
              ) : null}
              {/* Fresh canvas: no cards yet, but the days are real (dated, or
                  the Day 1..N scaffold) — point the traveler at Artemis
                  instead of a dead-end placeholder. */}
              {journal.nodeCount === 0 ? <EmptyJournalInvite /> : null}
              {journal.sections.map((section, idx) => {
                if (section.kind === "elision") {
                  // The skip affordance points past the span — at the day
                  // section that follows (none when the elision closes the
                  // journey).
                  const next = journal.sections[idx + 1];
                  return (
                    <ElisionMarker
                      key={`elide-${section.startDate}`}
                      elision={section}
                      jumpLabel={
                        next && next.kind === "day" ? next.label : null
                      }
                    />
                  );
                }
                return (
                  <DaySection
                    key={section.date}
                    section={section}
                    tz={tz}
                    pinned={pinned}
                    focusedNodeId={focusedNodeId}
                    subgraphChildren={subgraphChildren}
                    journeyThread={
                      journeyDays[idx]
                        ? {
                            fromPrev: journeyDays[idx - 1] === true,
                            toNext: journeyDays[idx + 1] === true,
                          }
                        : null
                    }
                    problems={problems}
                    onActivate={onActivate}
                    observe={observe}
                    dragEnabled={dragEnabled}
                    dragging={activeDragId !== null}
                    diffs={diffView?.annotations ?? null}
                    diffActive={diffActive}
                    diverged={diffView?.divergedDays.has(section.date) ?? false}
                    ghostCaption={
                      role === "advisor"
                        ? "not in this version"
                        : "not in your version"
                    }
                  />
                );
              })}
              {journal.nodeCount > 0 ? (
                <p className="mt-6 pl-[var(--spine-col)] font-serif text-[12px] italic text-ink/35" style={spineColStyle}>
                  — the end of the journey —
                </p>
              ) : null}
            </div>
          )}
        </div>

        {/* The right region beside the story on desktop. Below lg it collapses
            to the idle glance above the Journal (node detail deep-links to
            /item/[nodeId] instead) — same screen, responsive. Cinema fades it
            out with the rest of the chrome.
              · <2xl: the fixed 340px COCKPIT rail (medium tier); its "Open
                full" handle opens the modal.
              · 2xl+ : the cockpit still leads (following the scroll-active card
                cheaply); "Open full" EXPANDS the full CardDetailView BENEATH the
                cockpit and hard-locks focus until dismissed. The expanded stack
                flows into the page (not sticky), so it scrolls to the bottom
                normally — the lock keeps the card from swapping while you do. */}
        <aside
          data-testid="journal-rail"
          className={[
            "w-full transition-opacity duration-500 lg:order-3 lg:w-[340px] lg:shrink-0",
            cinemaMode ? "pointer-events-none opacity-0" : "opacity-100",
          ].join(" ")}
        >
          <div className={showInlineFull ? "flex flex-col gap-3" : "lg:sticky lg:top-4"}>
            <RightRail
              idle={railIdle}
              diffView={diffView}
              onToggleFull={inlineDetail ? toggleInlineDetail : null}
              fullOpen={showInlineFull}
            />
            {showInlineFull && inlineDetailNodeId ? (
              <div data-testid="journal-inline-detail">
                {/* Key by node so the detail's in-place editors (schedule day/
                    time, edit fields) reset per card — the panel instance
                    persists as the active node changes otherwise. Mirrors the
                    cockpit's `RailEditPanel key={active.id}`. */}
                <CardDetailView
                  key={inlineDetailNodeId}
                  nodeId={inlineDetailNodeId}
                  embedded
                  onDismiss={collapseInlineDetail}
                />
              </div>
            ) : null}
          </div>
        </aside>
      </div>

      {/* Phase-5 furniture — the more-below tail cue and cinema's scroll
          driver (chrome-aware: cinema fades or hides them). The day minimap
          now lives in-flow inside the Journal container above. */}
      <MoreBelowCue journal={journal} scrollRootRef={scrollRootRef} />
      <CinemaDriver scrollRootRef={scrollRootRef} />

      {/* The dragged card follows the cursor as a clone — the source only
          dims, so the absolute margin channel never breaks. */}
      <DragOverlay dropAnimation={null}>
        {activeDragNode ? (
          <div style={{ width: 300, cursor: "grabbing" }}>
            <NodeCard node={activeDragNode} tzOffsetHours={tz} />
          </div>
        ) : null}
      </DragOverlay>

      {/* "Make this yours?" — a trunk drag landed; the graph is untouched
          until the reader opts into their own version (the lazy-fork path). */}
      {forkOffer ? (
        <div
          data-testid="journal-fork-offer"
          className="fixed inset-x-0 bottom-6 z-50 flex justify-center px-4"
        >
          <div className="flex w-full max-w-md flex-col gap-2 rounded-lg border border-ink/15 bg-paper p-4 shadow-lg">
            <p className="font-serif text-[15px] text-ink">Make this yours?</p>
            <p className="font-sans text-[12px] leading-snug text-ink/60">
              {viewerOpenForkId
                ? "You already have a version of this trip — moves and edits live there."
                : `Moving “${forkOffer.title}” starts your own version of the trip. The official plan stays untouched until your advisor folds your changes in.`}
            </p>
            <div className="mt-1 flex justify-end gap-3">
              <button
                type="button"
                data-testid="journal-fork-offer-dismiss"
                onClick={() => setForkOffer(null)}
                className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50 transition-colors hover:text-ink"
              >
                Not now
              </button>
              <button
                type="button"
                data-testid="journal-fork-offer-confirm"
                onClick={confirmForkOffer}
                className="rounded-full bg-ink px-4 py-1.5 font-sans text-[10px] uppercase tracking-[0.16em] text-paper transition-opacity hover:opacity-90"
              >
                {viewerOpenForkId ? "Open my version" : "Start my version"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </DndContext>
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
  subgraphChildren,
  journeyThread = null,
  problems,
  onActivate,
  observe,
  dragEnabled,
  dragging,
  diffs = null,
  diffActive = false,
  diverged = false,
  ghostCaption = "not in your version",
}: {
  section: JournalDaySection;
  tz: number;
  pinned: boolean;
  focusedNodeId: string | null;
  /** Embedded subgraphs — a multi-day card's day children, by parent id. */
  subgraphChildren: Map<string, NodeResponse[]>;
  /** This day carries a packaged journey — wears the journey thread. The
   *  flags say whether the thread continues from the previous day section /
   *  into the next one, so it bridges headers, nights, and section gaps
   *  (computed over the WHOLE journal in JournalView — adjacency is not a
   *  per-day fact). Null = no journey through this day. */
  journeyThread?: { fromPrev: boolean; toNext: boolean } | null;
  problems: Map<string, JournalProblem>;
  onActivate: (nodeId: string) => void;
  observe: ReturnType<typeof useScrollActive>;
  /** Cards offer the drag gesture (editable fork / draft preview / the
   *  trunk's fork offer). Firmed cards + notes still refuse their own drag. */
  dragEnabled: boolean;
  /** A spine drag is in flight — materialize the drop slots (the gaps). */
  dragging: boolean;
  /** Diff-mode annotations, node id → change (phase 4); null when reading
   *  normally. */
  diffs?: Map<string, JournalNodeDiff> | null;
  /** Diff mode is on — insert affordances sit out (a reading/deciding mode). */
  diffActive?: boolean;
  /** This day diverges from the baseline (toJournalDiff's `divergedDays` —
   *  the same set the day rail's dots read) — wears the second thread. */
  diverged?: boolean;
  /** Role-aware ghost caption ("not in your/this version"). */
  ghostCaption?: string;
}) {
  // The gaps between cards are the drop slots; each assigns the sensible
  // slot time derived from its neighbours (journalEditing.ts — no pixel math).
  const slotMinutes = useMemo(
    () => dropSlotMinutes(cardBoundsOf(section.entries, tz)),
    [section.entries, tz],
  );

  const rows: ReactNode[] = [];
  let cardIdx = 0;
  for (const [i, entry] of section.entries.entries()) {
    if (entry.kind === "node" || entry.kind === "alt") {
      if (dragging) {
        rows.push(
          <DropSlot
            key={`slot-${section.date}-${cardIdx}`}
            id={journalSlotId(section.date, cardIdx)}
            dayKey={section.date}
            minute={slotMinutes[cardIdx] ?? SLOT_EMPTY_DAY_MIN}
          />,
        );
      }
      cardIdx += 1;
    }
    switch (entry.kind) {
      case "node":
        rows.push(
          <JournalNode
            key={entry.node.id}
            node={entry.node}
            tzOffsetHours={tz}
            active={focusedNodeId === entry.node.id}
            durationMinutes={entry.durationMinutes}
            subgraphChildren={subgraphChildren.get(entry.node.id) ?? []}
            onActivate={onActivate}
            observeRef={observe(entry.node.id)}
            dragEnabled={dragEnabled}
            problem={problems.get(entry.node.id) ?? null}
            bracket={entry.groupedWith ?? null}
            diff={diffs?.get(entry.node.id) ?? null}
            journey={entry.journey ?? null}
          />,
        );
        break;
      case "ghost":
        // A trunk-only row (diff mode) — a ghost at its trunk time.
        rows.push(
          <JournalGhostNode
            key={entry.node.id}
            node={entry.node}
            active={focusedNodeId === entry.node.id}
            caption={ghostCaption}
            onActivate={onActivate}
            observeRef={observe(entry.node.id)}
          />,
        );
        break;
      case "alt":
        rows.push(
          <JournalAltGroup
            key={`alt-${entry.groupKey}`}
            nodes={entry.nodes}
            tzOffsetHours={tz}
            focusedNodeId={focusedNodeId}
            subgraphChildren={subgraphChildren}
            onActivate={onActivate}
            observeRef={observe}
            problems={problems}
            diffs={diffs ?? undefined}
          />,
        );
        break;
      case "gap":
        rows.push(
          <GapSegment
            key={`gap-${section.date}-${i}`}
            minutes={entry.minutes}
            startHour={entry.startHour}
          />,
        );
        break;
      case "quiet":
        rows.push(
          <VirtualNode
            key={entry.id}
            caption={entry.caption}
            minutes={entry.minutes}
            startHour={entry.startHour}
          />,
        );
        break;
    }
  }
  if (dragging) {
    rows.push(
      <DropSlot
        key={`slot-${section.date}-end`}
        id={journalSlotId(section.date, cardIdx)}
        dayKey={section.date}
        minute={slotMinutes[cardIdx] ?? SLOT_EMPTY_DAY_MIN}
      />,
    );
  }

  // A diverged day (any annotated card or ghost) wears the slim dashed SECOND
  // THREAD beside the spine — a region cue, never a split (that vocabulary
  // belongs to alternatives). Lifted into toJournalDiff (phase 5) so the day
  // rail's divergence dots read the exact same derivation.
  const hasDivergence = diverged;

  // The JOURNEY THREAD — a packaged multi-day experience runs through this
  // day: a solid second line right of the spine, the rail the beat rows sit
  // on (they indent onto it). ONE unbroken line across the whole run: on a
  // continuing day it spans the full section (behind the day rule, like the
  // spine), and while the journey goes on it reaches through the section gap
  // to meet the next day's thread — through the night, never restarting.
  const journeyThreadEl = journeyThread ? (
    <span
      aria-hidden
      data-testid="journal-journey-thread"
      data-from-prev={journeyThread.fromPrev ? "true" : undefined}
      data-to-next={journeyThread.toNext ? "true" : undefined}
      title="Part of a packaged journey"
      className={[
        "absolute top-0 w-0 border-l-2 border-ink/15",
        journeyThread.toNext ? "-bottom-2" : "bottom-0",
      ].join(" ")}
      style={{ left: SPINE_COL_PX / 2 + JOURNEY_INDENT_PX }}
    />
  ) : null;

  return (
    <section data-testid="journal-day" data-date={section.date} className="relative">
      {/* Alternate days wear a whisper of a wash — a reading aid, keyed to the
          scaffold index so the alternation tracks calendar days even across
          elisions. Painted as an overhanging layer so the grid stays put. */}
      {section.index % 2 === 1 ? (
        <span
          aria-hidden
          data-testid="journal-day-tint"
          className="absolute -inset-x-3 inset-y-0 rounded-lg bg-ink/[0.03]"
        />
      ) : null}
      {/* The continuous spine — one line the circles sit on. It spans the
          whole section (behind the day rule, which crosses it) and reaches
          into the gap below so the line never breaks at a day boundary. */}
      <span
        aria-hidden
        className="absolute -bottom-2 top-0 w-px bg-ink/15"
        style={{ left: SPINE_COL_PX / 2 }}
      />
      {/* A journey arriving from the previous day: its thread spans the whole
          section (behind the day rule, exactly like the spine) so it meets the
          previous section's overhang without a break. */}
      {journeyThread?.fromPrev ? journeyThreadEl : null}
      <DayHeader label={section.label} date={section.date} datesPinned={pinned} />
      <div className="relative flex flex-col gap-2 py-3" style={spineColStyle}>
        {/* Diff mode's diverged-region cue: a second, dashed thread running
            alongside the spine through this day. */}
        {hasDivergence ? (
          <span
            aria-hidden
            data-testid="journal-diff-thread"
            className="absolute bottom-0 top-0 w-0 border-l border-dashed border-brand/45"
            style={{ left: SPINE_COL_PX / 2 - 6 }}
          />
        ) : null}
        {/* The journey STARTING on this day: the thread opens below the day
            rule (the diff thread sits left of the spine; this one right). */}
        {journeyThread && !journeyThread.fromPrev ? journeyThreadEl : null}
        {rows}
        {/* The `+`-on-the-line: each day closes with the quiet insert
            affordance — Note only on the trunk; the Collection-first picker
            on an editable fork (phase 3). Content lands after the day's last
            card (the same slot arithmetic the drops use). Diff mode is a
            reading/deciding pass — the line offers nothing while it's on
            (margin notes and the rail's note stay open). */}
        {!diffActive ? (
          <AddNoteOnLine
            dayKey={section.date}
            insertMinute={slotMinutes[slotMinutes.length - 1] ?? SLOT_EMPTY_DAY_MIN}
          />
        ) : null}
        {section.night ? (
          <NightSegment title={section.night.node?.title} />
        ) : null}
      </div>
    </section>
  );
}

// A gap between cards, materialized as a drop target while a drag is in
// flight. Wears the minute it would assign when hovered — quiet otherwise.
function DropSlot({
  id,
  dayKey,
  minute,
}: {
  id: string;
  dayKey: string;
  minute: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data: { dayKey, minute } });
  return (
    <div
      ref={setNodeRef}
      data-testid="journal-drop-slot"
      data-minute={minute}
      data-over={isOver ? "true" : "false"}
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4"
      style={spineColStyle}
    >
      <div className="flex justify-center">
        <span
          aria-hidden
          className={[
            "z-10 block h-2 w-2 rounded-full transition-colors",
            isOver ? "bg-brand" : "border border-ink/25 bg-paper",
          ].join(" ")}
        />
      </div>
      <div
        className={[
          "flex items-center rounded-md border border-dashed px-3 transition-all",
          isOver ? "h-10 border-brand bg-[rgba(245,112,31,0.06)]" : "h-6 border-ink/15",
        ].join(" ")}
      >
        <span
          className={[
            "font-sans text-[10px] uppercase tracking-[0.16em]",
            isOver ? "text-brand" : "text-transparent",
          ].join(" ")}
        >
          {isOver ? `Move here · ${minuteLabel(minute)}` : ""}
        </span>
      </div>
    </div>
  );
}

// The fresh-canvas invitation (traveler/self-serve empty journal): the days
// below are real and each carries its (+), but the story starts with the
// conversation — so this points at Artemis rather than at the empty spine.
// `openConcierge` reveals the summoned overlay below 1100px and un-collapses
// the in-flow column above it, so the CTA always lands the traveler in the chat.
function EmptyJournalInvite() {
  const { openConcierge } = useConciergeControl();
  return (
    <div
      data-testid="journal-empty-invite"
      className="mb-6 rounded-lg border border-ink/10 bg-ink/[0.03] px-6 py-8 text-center"
    >
      <p className="font-serif text-xl leading-snug text-ink/80">
        Wide open possibilities. Let&rsquo;s dream together!
      </p>
      <p className="mx-auto mt-2 max-w-md font-sans text-sm leading-relaxed text-ink/55">
        Keep the conversation going and the journal fills itself, or press a
        day&rsquo;s <span className="font-medium text-ink/70">+</span> to write
        the first line yourself.
      </p>
      <button
        type="button"
        onClick={openConcierge}
        className="mt-5 inline-flex items-center gap-2 rounded-sm bg-brand px-5 py-2.5 font-sans text-[11px] uppercase tracking-[0.22em] text-paper shadow-sm transition hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
      >
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-paper/90" />
        Talk to Artemis
      </button>
    </div>
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
