"use client";

// The Journal's day rail (traveler-journal design, phase 5) — a slim floating
// minimap of the journey: one dot per day, elisions compressed to a dashed
// tick, the current day highlighted, "Day N of M" beside it. Click jumps to
// the day header (smooth; instant under `prefers-reduced-motion`).
//
// Indexing is the `dayRailModel.ts` derivation over `toJournal` output — the same
// 0-based scaffold the day headers and elision markers read — so the rail and
// the spine can never disagree about which day is which (tested invariant).
// In diff mode a diverged day's dot wears a quiet brand ring (fed by the SAME
// `divergedDays` set as the spine's second thread).
//
// Same screen, responsive: a vertical rail on the left edge ≥lg; below lg the
// same dots become a slim floating bottom pill (the Journal's DayStrip — a
// horizontal, auto-centering strip, adapted to jump-not-page). Cinema fades
// the rail out with the rest of the chrome.

import { useEffect, useMemo, useRef, type RefObject } from "react";

import { itineraryGraphStore } from "../../store/itineraryGraphStore";

import { dayIndexByNode, dayRailItems, type DayRailItem } from "./dayRailModel";
import { prefersReducedMotion, scrollBehaviorFor } from "./motion";
import type { Journal } from "./toJournal";

export function DayRail({
  journal,
  totalDays,
  divergedDays = null,
  scrollRootRef,
}: {
  journal: Journal;
  /** The scaffold length — the "of M" in "Day N of M". */
  totalDays: number;
  /** Diff mode's diverged-day set (toJournalDiff) — null when reading
   *  normally. */
  divergedDays?: ReadonlySet<string> | null;
  scrollRootRef?: RefObject<HTMLElement | null> | undefined;
}) {
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);

  const items = useMemo(() => dayRailItems(journal), [journal]);
  const nodeDay = useMemo(() => dayIndexByNode(journal), [journal]);

  const firstDay = items.find(
    (i): i is Extract<DayRailItem, { kind: "day" }> => i.kind === "day",
  );
  const current =
    (focusedNodeId ? nodeDay.get(focusedNodeId) : undefined) ??
    firstDay?.index ??
    0;

  // The mobile strip auto-centers the current dot (the DayStrip idiom).
  const stripRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = stripRef.current?.querySelector<HTMLElement>(
      `[data-index="${current}"]`,
    );
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({
        inline: "center",
        block: "nearest",
        behavior: scrollBehaviorFor(prefersReducedMotion()),
      });
    }
  }, [current]);

  // Nothing to navigate on a blank journal or a day trip.
  if (journal.nodeCount === 0 || totalDays < 2) return null;

  const jump = (item: DayRailItem) => {
    const scope: ParentNode = scrollRootRef?.current ?? document;
    const sel =
      item.kind === "day"
        ? `[data-testid="journal-day"][data-date="${item.date}"]`
        : `[data-testid="journal-elision"][data-start-date="${item.startDate}"]`;
    const el = scope.querySelector<HTMLElement>(sel);
    if (!el || typeof el.scrollIntoView !== "function") return;
    el.scrollIntoView({
      behavior: scrollBehaviorFor(prefersReducedMotion()),
      block: "start",
    });
  };

  // Cinema: the rail is chrome — it fades with the rest.
  const chrome = cinemaMode
    ? "pointer-events-none opacity-0"
    : "opacity-100";

  const dot = (item: DayRailItem, horizontal: boolean) => {
    if (item.kind === "elision") {
      const label = `Days ${item.startIndex + 1}–${item.endIndex + 1} · open`;
      return (
        <button
          key={`elide-${item.startDate}`}
          type="button"
          onClick={() => jump(item)}
          title={label}
          aria-label={`Jump to ${label.toLowerCase()}`}
          data-testid="journal-day-rail-elision"
          className="group flex h-4 w-4 shrink-0 items-center justify-center"
        >
          <span
            aria-hidden
            className={[
              "block border-dashed border-ink/30 transition-colors group-hover:border-ink/60",
              horizontal ? "h-px w-3.5 border-t" : "h-3.5 w-px border-l",
            ].join(" ")}
          />
        </button>
      );
    }
    const active = item.index === current;
    const diverged = divergedDays?.has(item.date) ?? false;
    return (
      <button
        key={item.date}
        type="button"
        onClick={() => jump(item)}
        title={item.label}
        aria-label={`Jump to ${item.label}`}
        aria-current={active ? "step" : undefined}
        data-testid="journal-day-rail-dot"
        data-index={item.index}
        data-diverged={diverged ? "true" : undefined}
        className="group flex h-4 w-4 shrink-0 items-center justify-center"
      >
        <span
          aria-hidden
          className={[
            "rounded-full transition-all",
            active
              ? "h-2.5 w-2.5 bg-brand"
              : diverged
                ? "h-2 w-2 border border-brand/60 bg-brand/20 group-hover:bg-brand/45"
                : "h-1.5 w-1.5 bg-ink/25 group-hover:bg-ink/55",
          ].join(" ")}
        />
      </button>
    );
  };

  return (
    <>
      {/* ≥lg: the vertical rail, floating on the left edge. */}
      <nav
        aria-label="Journey days"
        data-testid="journal-day-rail"
        className={`fixed left-2 top-1/2 z-30 hidden -translate-y-1/2 flex-col items-center transition-opacity duration-500 lg:flex xl:left-4 ${chrome}`}
      >
        <div className="flex max-h-[58vh] flex-col items-center gap-1 overflow-y-auto py-1 [scrollbar-width:none]">
          {items.map((item) => dot(item, false))}
        </div>
        <p
          data-testid="journal-day-rail-label"
          className="mt-2 text-center font-sans text-[9px] uppercase leading-tight tracking-[0.14em] text-ink/50"
        >
          <span className="block">Day {current + 1}</span>
          <span className="block text-ink/35">of {totalDays}</span>
        </p>
      </nav>

      {/* <lg: the same dots as a slim floating bottom pill (DayStrip, adapted:
          it jumps within one continuous scroll instead of paging days). */}
      <nav
        aria-label="Journey days"
        data-testid="journal-day-rail-mobile"
        className={`pointer-events-none fixed inset-x-0 bottom-3 z-30 flex justify-center px-4 transition-opacity duration-500 lg:hidden ${chrome}`}
      >
        <div
          className={[
            "flex max-w-full items-center gap-2 rounded-full border border-ink/15 bg-paper/90 px-3 py-1.5 shadow-sm backdrop-blur-sm",
            cinemaMode ? "" : "pointer-events-auto",
          ].join(" ")}
        >
          <div
            ref={stripRef}
            className="flex max-w-[52vw] items-center gap-0.5 overflow-x-auto [scrollbar-width:none]"
          >
            {items.map((item) => dot(item, true))}
          </div>
          <span className="shrink-0 font-sans text-[9px] uppercase tracking-[0.14em] text-ink/50">
            Day {current + 1} of {totalDays}
          </span>
        </div>
      </nav>
    </>
  );
}
