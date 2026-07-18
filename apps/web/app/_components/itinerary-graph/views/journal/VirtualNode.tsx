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
import { ChevronDown } from "lucide-react";
import { useRef, useState } from "react";

import { sunColorAtHour } from "../../model/sun";
import { formatDuration } from "../../model/time";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { elisionExpandSeconds, prefersReducedMotion, scrollBehaviorFor } from "./motion";
import type { JournalElision } from "./toJournal";
import { HourTickMark, hourTicks, QuietCircle, SPINE_COL_PX } from "./Spine";

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

// The gap's lane grows with the journal zoom so "time passing" reads, but stays
// clamped: a short gap never collapses to nothing and an open day never runs
// off the page.
const GAP_LANE_MIN_PX = 14;
const GAP_LANE_MAX_PX = 240;

function gapLaneHeight(minutes: number, pxPerMinute: number): number {
  return Math.min(
    GAP_LANE_MAX_PX,
    Math.max(GAP_LANE_MIN_PX, minutes * pxPerMinute),
  );
}

/** True when a gap spans into evening / night (≥18:00 or before 06:00) —
 *  drives the dusk wash so "evening" reads without a bar. */
function crossesDusk(startHour: number, minutes: number): boolean {
  const end = startHour + minutes / 60;
  for (let h = Math.floor(startHour); h <= Math.ceil(end); h += 1) {
    const wrapped = ((h % 24) + 24) % 24;
    if (wrapped >= 18 || wrapped < 6) return true;
  }
  return false;
}

/**
 * The shared gap lane: the spine's gutter over an empty stretch, sized to the
 * time it covers, wearing occasional hour ticks and — through evening/night —
 * the dusk wash. `children` is the caption beside it (quiet moments carry one;
 * a plain short gap doesn't).
 */
function GapLane({
  minutes,
  startHour,
  testid,
  children,
}: {
  minutes: number;
  startHour: number;
  testid: string;
  children?: React.ReactNode;
}) {
  const pxPerMinute = itineraryGraphStore.useStore((s) => s.journalPxPerMinute);
  const height = gapLaneHeight(minutes, pxPerMinute);
  const ticks = hourTicks(startHour, minutes);
  const dusk = crossesDusk(startHour, minutes);
  const end = startHour + minutes / 60;
  const wash = dusk
    ? `linear-gradient(180deg, ${sunColorAtHour(startHour)} 0%, ${sunColorAtHour((startHour + end) / 2)} 50%, ${sunColorAtHour(end)} 100%)`
    : undefined;
  return (
    <div
      data-testid={testid}
      data-minutes={minutes}
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] gap-x-4"
      style={spineColStyle}
    >
      <div className="relative flex justify-center" style={{ height }}>
        {/* Dusk wash — a fading sky behind the gutter through evening/night. */}
        {wash ? (
          <span
            aria-hidden
            data-testid="journal-dusk-wash"
            className="absolute inset-y-0 w-6 rounded-md"
            style={{
              background: wash,
              opacity: 0.28,
              maskImage:
                "radial-gradient(120% 100% at 50% 50%, #000 40%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(120% 100% at 50% 50%, #000 40%, transparent 100%)",
            }}
          />
        ) : null}
        {/* Occasional hour ticks — a faint mark + tiny label right of the
            spine, the same ruler the duration bars wear so gaps and cards read
            as one continuous measure of the day. */}
        {ticks.map((t) => (
          <HourTickMark key={t.hour} hour={t.hour} top={`${t.frac * 100}%`} />
        ))}
      </div>
      {children ? (
        <div className="flex items-center">{children}</div>
      ) : (
        <span />
      )}
    </div>
  );
}

/** A long gap: a whispered caption beside a time-scaled lane with hour ticks. */
export function VirtualNode({
  caption,
  minutes,
  startHour = 0,
}: {
  caption: string;
  minutes: number;
  /** Local clock hour the span opens on — places its hour ticks + dusk wash. */
  startHour?: number;
}) {
  const isFullDay = minutes >= 24 * 60;
  return (
    <GapLane minutes={minutes} startHour={startHour} testid="journal-quiet">
      <p className="flex items-center gap-2 font-serif text-[13px] italic text-ink/45">
        <QuietCircle />~ {caption.toLowerCase()}
        {isFullDay ? "" : ` · ${formatDuration(minutes)}`} ~
      </p>
    </GapLane>
  );
}

/** A short gap: the spine continues, its lane sized to the minutes it covers,
 *  wearing an hour tick when one falls inside. */
export function GapSegment({
  minutes,
  startHour = 0,
}: {
  minutes: number;
  startHour?: number;
}) {
  return (
    <GapLane minutes={minutes} startHour={startHour} testid="journal-gap" />
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
            className="inline-flex items-center gap-1.5 rounded-full border border-ink/15 bg-ink/[0.04] px-3.5 py-1.5 text-left font-sans text-[11px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:border-ink/40 hover:bg-ink/[0.08] hover:text-ink"
          >
            <ChevronDown
              aria-hidden
              className={[
                "h-3.5 w-3.5 shrink-0 transition-transform",
                expanded ? "rotate-180" : "",
              ].join(" ")}
            />
            <span className="font-medium">
              {expanded ? "Hide" : "Show"} {elision.dayCount} open day
              {elision.dayCount === 1 ? "" : "s"}
            </span>
            <span aria-hidden className="text-ink/35">
              · {rangeLabel}
              {elision.lodging ? ` · at ${elision.lodging.title}` : ""}
            </span>
          </button>
          {jumpLabel ? (
            <button
              type="button"
              onClick={skip}
              data-testid="journal-elision-skip"
              className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45 underline-offset-4 transition-colors hover:text-ink hover:underline"
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
                    {d.label} —{" "}
                    {elision.lodging ? `at ${elision.lodging.title}` : "open"}
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
