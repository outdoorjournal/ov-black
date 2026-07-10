"use client";

// The Journal's derived (never-persisted) moments: the quiet-gap virtual node,
// the plain short-gap spine segment, and the multi-day elision marker. All are
// client-side derivations from `toJournal` — nothing here exists in the graph.
//
// Phase 5 polishes the elision: the expand/collapse animates (height, framer-
// motion — instant under `prefers-reduced-motion`), and a JUMP affordance
// skips past the open span to the next day section. The marker also wears
// `data-start-date` / `data-day-count` so the day rail and the more-below cue
// can address it with the SAME day indexing the derivation produced.

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useRef, useState } from "react";

import { formatDuration } from "../../model/time";
import { elisionExpandSeconds, prefersReducedMotion, scrollBehaviorFor } from "./motion";
import type { JournalElision } from "./toJournal";
import { QuietCircle, SPINE_COL_PX } from "./Spine";

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

/** A long gap: small circle on the line, a whispered caption, no card. */
export function VirtualNode({
  caption,
  minutes,
}: {
  caption: string;
  minutes: number;
}) {
  const isFullDay = minutes >= 24 * 60;
  return (
    <div
      data-testid="journal-quiet"
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 py-2"
      style={spineColStyle}
    >
      <div className="flex justify-center">
        <QuietCircle />
      </div>
      <p className="font-serif text-[13px] italic text-ink/45">
        ~ {caption.toLowerCase()}
        {isFullDay ? "" : ` · ${formatDuration(minutes)}`} ~
      </p>
    </div>
  );
}

/** A short gap: the spine simply continues, a touch longer. */
export function GapSegment({ minutes }: { minutes: number }) {
  return (
    <div
      aria-hidden
      data-testid="journal-gap"
      className={minutes >= 60 ? "h-8" : "h-4"}
    />
  );
}

/**
 * A multi-day empty span, collapsed: "Days 12–18 · 7 open days". Expandable in
 * place to walk the individual days (each an open day on the spine) — the
 * expand animates (instant under reduced motion) — plus a jump affordance that
 * skips past the span to the next day section on the spine.
 */
export function ElisionMarker({
  elision,
  jumpLabel = null,
}: {
  elision: JournalElision;
  /** The next day section's label ("Day 19") — renders the skip affordance;
   *  null when the elision closes the journey (nothing to skip to). */
  jumpLabel?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const reduced = Boolean(useReducedMotion());
  const sectionRef = useRef<HTMLElement>(null);
  const rangeLabel =
    elision.dayCount === 1
      ? elision.startLabel
      : `${elision.startLabel.replace(/^Day /, "Days ")}–${elision.endLabel.replace(/^Day /, "")}`;

  // Skip past the span: the marker's next sibling on the spine is the day
  // section that follows the elided run.
  const skip = () => {
    const next = sectionRef.current?.nextElementSibling;
    if (next && typeof next.scrollIntoView === "function") {
      next.scrollIntoView({
        behavior: scrollBehaviorFor(prefersReducedMotion()),
        block: "start",
      });
    }
  };

  return (
    <section
      ref={sectionRef}
      data-testid="journal-elision"
      data-start-date={elision.startDate}
      data-day-count={elision.dayCount}
      className="py-3"
    >
      <div
        className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4"
        style={spineColStyle}
      >
        <div aria-hidden className="flex justify-center">
          <span className="relative z-10 flex h-10 items-center bg-paper py-1 text-[10px] leading-none tracking-[0.3em] text-ink/35 [writing-mode:vertical-rl]">
            · · ·
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            data-testid="journal-elision-toggle"
            className="rounded-full border border-dashed border-ink/25 px-3 py-1 text-left font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 transition-colors hover:border-ink/45 hover:text-ink"
          >
            {rangeLabel} · {elision.dayCount} open days
            <span aria-hidden className="ml-2">
              {expanded ? "–" : "+"}
            </span>
          </button>
          {jumpLabel ? (
            <button
              type="button"
              onClick={skip}
              data-testid="journal-elision-skip"
              className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/40 underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              skip to {jumpLabel} ↓
            </button>
          ) : null}
        </div>
      </div>
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            key="days"
            data-testid="journal-elision-days"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{
              duration: elisionExpandSeconds(reduced),
              ease: "easeInOut",
            }}
            className="overflow-hidden"
          >
            <div className="mt-2 flex flex-col">
              {elision.days.map((d) => (
                <div
                  key={d.date}
                  className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 py-1.5"
                  style={spineColStyle}
                >
                  <div className="flex justify-center">
                    <QuietCircle />
                  </div>
                  <p className="font-serif text-[12px] italic text-ink/40">
                    {d.label} — open
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
