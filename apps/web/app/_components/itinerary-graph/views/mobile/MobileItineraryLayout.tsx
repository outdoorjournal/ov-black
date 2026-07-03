"use client";

// The mobile presentation of the itinerary — NOT a separate route or a
// user-selectable "view", just the small-screen layout of the SAME store the
// desktop view reads. ItineraryGraphView renders this below `md` and the
// desktop view above it, toggled with `display` utilities, so the switch is
// seamless on resize with no reload.
//
// Shape (the traveler's vision): pick the day up top (a swipeable strip), the
// timeline for that day sits underneath as a vertical card feed, and the
// concierge lives in a drag-up bottom sheet. Swiping the timeline left/right
// pages days and keeps the strip in sync; a proposal that lands on another day
// surfaces a one-tap jump in the sheet handle.

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { BuilderEmptyState } from "../../shared/BuilderEmptyState";
import { VersionSwitcher } from "../../shared/VersionSwitcher";
import { Card } from "../../shared/ExpandedCard";
import { NotesPanel } from "../../shared/NotesPanel";
import { attachedNotesByHost } from "../../shared/attachedNotes";
import type {
  ItineraryTimeline,
  NodeResponse,
} from "../../model/horizontalTypes";
import {
  dayIndexForNode,
  groupNodesByDay,
} from "../../shared/groupNodesByDay";
import {
  itineraryGraphStore,
  selectCanLeaveNote,
} from "../../store/itineraryGraphStore";

import { ConciergeSheet } from "./ConciergeSheet";
import { DayStrip } from "./DayStrip";
import { DayTimeline } from "./DayTimeline";

interface MobileItineraryLayoutProps {
  timeline: ItineraryTimeline;
  baselineTitle?: string | null;
  /** Fill the flex parent (below the AppHeader) instead of the whole viewport. */
  embedded?: boolean;
}

export function MobileItineraryLayout({
  timeline,
  embedded = false,
}: MobileItineraryLayoutProps) {
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const pendingProposals = itineraryGraphStore.useStore(
    (s) => s.pendingProposals,
  );
  const flashNodeId = itineraryGraphStore.useStore((s) => s.flashNodeId);
  const role = itineraryGraphStore.useStore((s) => s.role);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  const tz = timeline.timezoneOffsetHours;
  const groups = useMemo(
    () => groupNodesByDay([...nodes, ...pendingProposals], timeline.days, tz),
    [nodes, pendingProposals, timeline.days, tz],
  );
  const attachedNotes = useMemo(() => attachedNotesByHost(nodes), [nodes]);
  const canLeaveNote = itineraryGraphStore.useStore(selectCanLeaveNote);
  const addAttachedNote = itineraryGraphStore.useStore((s) => s.addAttachedNote);
  const addFreeStandingNote = itineraryGraphStore.useStore(
    (s) => s.addFreeStandingNote,
  );

  const [activeDay, setActiveDay] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [hint, setHint] = useState<{ dayIndex: number; label: string } | null>(
    null,
  );
  const pagerRef = useRef<HTMLDivElement>(null);

  // Page the body to a day. The resulting scroll drives `activeDay` back, so
  // taps (strip) and swipes (body) converge on one source of truth.
  const goToDay = useCallback((index: number) => {
    const el = pagerRef.current;
    if (!el) return;
    el.scrollTo({ left: index * el.clientWidth, behavior: "smooth" });
  }, []);

  const onPagerScroll = useCallback(() => {
    const el = pagerRef.current;
    if (!el || el.clientWidth === 0) return;
    const index = Math.round(el.scrollLeft / el.clientWidth);
    setActiveDay((prev) => (prev === index ? prev : index));
  }, []);

  // Once the hinted day is in view, the hint has done its job.
  useEffect(() => {
    if (hint && hint.dayIndex === activeDay) setHint(null);
  }, [hint, activeDay]);

  // A freshly-arrived proposal on a day other than the active one → offer a jump.
  const prevProposalIds = useRef<Set<string>>(new Set());
  useEffect(() => {
    const fresh = pendingProposals.filter(
      (p) => !prevProposalIds.current.has(p.id),
    );
    prevProposalIds.current = new Set(pendingProposals.map((p) => p.id));
    const latest = fresh[fresh.length - 1];
    if (!latest) return;
    const idx = dayIndexForNode(latest, timeline.days, tz);
    if (idx < 0 || idx === activeDay) return;
    setHint({ dayIndex: idx, label: timeline.days[idx]?.label ?? "" });
  }, [pendingProposals, tz, timeline.days, activeDay]);

  const expandedNode: NodeResponse | null = useMemo(() => {
    if (!expandedId) return null;
    return (
      nodes.find((n) => n.id === expandedId) ??
      pendingProposals.find((n) => n.id === expandedId) ??
      null
    );
  }, [expandedId, nodes, pendingProposals]);

  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpandedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expandedId]);

  // The traveler joins the shared client thread; an advisor on a phone gets
  // their private workspace rather than being dropped into the client's.
  const audience = role === "advisor" ? "advisor" : "traveler";
  const clientId = timeline.itinerary.client_id;

  return (
    <div
      className={
        "flex w-screen flex-col overflow-hidden bg-paper text-ink " +
        (embedded ? "min-h-0 flex-1" : "h-[100dvh]")
      }
    >
      <header className="flex shrink-0 items-start justify-between gap-2 border-b border-ink/10 px-4 pb-1.5 pt-3">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
            OV Black · Itinerary
          </div>
          <div className="font-serif text-lg leading-tight text-ink">
            {timeline.label}
            {timeline.subtitle ? (
              <span className="ml-2 text-[12px] italic text-ink/55">
                {timeline.subtitle}
              </span>
            ) : null}
          </div>
        </div>
        <div className="shrink-0 pt-1">
          <VersionSwitcher />
        </div>
      </header>

      <DayStrip groups={groups} activeIndex={activeDay} onSelect={goToDay} />

      {/* Horizontal pager — one full-width page per day, each scrolls its own
          card feed vertically. snap-mandatory makes swipes land on a day. The
          relative wrapper carries the empty-state overlay when nothing's on the
          board yet. */}
      <div className="relative flex min-h-0 flex-1">
      <div
        ref={pagerRef}
        onScroll={onPagerScroll}
        className="flex h-full w-full snap-x snap-mandatory overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {groups.map((g) => (
          <section
            key={g.date}
            className="h-full w-screen shrink-0 snap-center overflow-y-auto"
          >
            <DayTimeline
              group={g}
              tzOffsetHours={tz}
              flashNodeId={flashNodeId}
              onCardClick={(id) => setExpandedId(id)}
              attachedNotes={attachedNotes}
              canLeaveNote={canLeaveNote}
              onAddDayNote={addFreeStandingNote}
            />
          </section>
        ))}
      </div>
        {nodes.length === 0 && pendingProposals.length === 0 ? (
          <BuilderEmptyState hint="sheet" />
        ) : null}
      </div>

      <ConciergeSheet
        audience={audience}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        clientId={clientId}
        itineraryId={timeline.itinerary.id}
        pendingCount={pendingProposals.length}
        proposalHint={hint}
        onJumpToProposal={() => {
          if (hint) {
            goToDay(hint.dayIndex);
            setHint(null);
          }
        }}
      />

      <AnimatePresence>
        {expandedNode ? (
          <motion.div
            key="m-expand"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="fixed inset-0 z-[60] flex items-end justify-center bg-ink/45 p-4 backdrop-blur-sm"
            onClick={() => setExpandedId(null)}
          >
            <motion.div
              initial={{ y: 24 }}
              animate={{ y: 0 }}
              exit={{ y: 24 }}
              className="w-full max-w-md"
              onClick={(e) => e.stopPropagation()}
            >
              <Card node={expandedNode} mood={timeline.mood} />
              {expandedNode.type !== "note" ? (
                <NotesPanel
                  notes={attachedNotes.get(expandedNode.id) ?? []}
                  canAdd={canLeaveNote}
                  onAddNote={(text) => addAttachedNote(expandedNode.id, text)}
                />
              ) : null}
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
