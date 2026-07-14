"use client";

// The Journal's spine furniture: the node circle (a miniature of the card's
// identity — type accent + icon from the shared tokens, status worn as the
// ring) and the night segment (the spine itself darkening between days, per
// the `night_bar` treatment). The continuous line is drawn by the section
// container in JournalView; these pieces sit ON it.

import { sunColorAtHour } from "../../model/sun";
import {
  BRAND_RGB,
  STATUS_TOKENS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "../../shared/cards/tokens";
import { prefersReducedMotion, scrollBehaviorFor } from "./motion";

/** Width of the spine gutter column — JournalView's grid + line share it. */
export const SPINE_COL_PX = 44;

/** How far a journey beat's whole row (circle, bar, card) shifts right of the
 *  main spine — the offset puts the beat circles ON the journey thread, so the
 *  thread reads as the sub-journey's own rail. The thread shares this value. */
export const JOURNEY_INDENT_PX = 12;

// ── Duration bars (traveler-journal) ──────────────────────────────────
// Each activity hangs a colored bar off its spine circle, stretching down the
// gutter to show how long it runs — the shape the night used to own, now worn
// by the events themselves. In-flow (not absolute) so a long event's bar grows
// its row and nudges the next card down: that displacement IS the sense of time
// passing, alongside the hour ticks in the gaps. Clamped so a short beat still
// reads and an all-day journey leg doesn't run off the page.
export const JOURNAL_BAR_MIN_PX = 6;
export const JOURNAL_BAR_MAX_PX = 340;
export const JOURNAL_BAR_WIDTH_PX = 5;
// Past this drawn length the bar has run far enough below its card (a multi-day
// leg, an all-day span) that the card is well offscreen — so its tail carries a
// scroll-back-to-the-card button, mirroring the horizontal planner.
export const JOURNAL_BAR_SCROLLBACK_PX = 200;

/** Pixel length of a duration bar at the current journal zoom, clamped. */
export function journalBarHeight(minutes: number, pxPerMinute: number): number {
  const raw = Math.max(0, minutes) * pxPerMinute;
  return Math.min(JOURNAL_BAR_MAX_PX, Math.max(JOURNAL_BAR_MIN_PX, raw));
}

// Status → the circle's ring, mirroring the card-status vocabulary without
// relying on color alone (each non-pending status also wears its glyph badge):
//   pending    soft hairline ring
//   approved   solid accent ring + ✓ badge
//   booked     solid ink ring + ⚿ badge
//   confirmed  double ring + ◉ badge
//   discarded  grayscale, dashed feel via opacity
function ringShadow(
  status: StatusKind,
  accent: string,
  active: boolean,
  problem: boolean,
): string {
  const activeGlow = active ? `, 0 0 0 5px rgba(${BRAND_RGB}, 0.28)` : "";
  // Problem state: the RED ring outranks the status ring (the status still
  // reads from the badge glyph). Color is never the only cue — the ⚠ glyph
  // sits outside the circle (rendered by JournalNode) and a one-line caption
  // runs under the card.
  if (problem) return `0 0 0 2px #b3261e${activeGlow}`;
  switch (status) {
    case "approved":
      return `0 0 0 2px ${accent}${activeGlow}`;
    case "booked":
      return `0 0 0 2px #0a0a0a${activeGlow}`;
    case "confirmed":
      return `0 0 0 2px #0a0a0a, 0 0 0 4px rgba(10,10,10,0.35)${activeGlow}`;
    default:
      return `0 0 0 1px rgba(10,10,10,0.18)${activeGlow}`;
  }
}

const STATUS_GLYPH: Partial<Record<StatusKind, string>> = {
  approved: "✓",
  booked: "⚿",
  confirmed: "◉",
};

export function SpineCircle({
  kind,
  status,
  active,
  problem = false,
}: {
  kind: CardKind;
  status: StatusKind;
  active: boolean;
  /** Problem state: red ring (the non-color cues live beside the circle). */
  problem?: boolean;
}) {
  const token = TYPE_TOKENS[kind];
  return (
    <span
      role="img"
      aria-label={`${token.label} — ${STATUS_TOKENS[status].label}${problem ? " — needs attention" : ""}`}
      data-testid="journal-spine-circle"
      data-kind={kind}
      data-status={status}
      data-problem={problem ? "true" : undefined}
      className={[
        "relative z-10 flex h-7 w-7 items-center justify-center rounded-full text-paper",
        "transition-transform duration-200",
        active ? "scale-110" : "",
        status === "discarded" ? "opacity-50 grayscale" : "",
      ].join(" ")}
      style={{
        backgroundColor: token.accent,
        boxShadow: ringShadow(status, token.accent, active, problem),
      }}
    >
      <token.Icon size={13} strokeWidth={1.8} aria-hidden />
      {STATUS_GLYPH[status] ? (
        <span
          aria-hidden
          className="absolute -bottom-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full border border-ink/20 bg-paper text-[8px] leading-none text-ink"
        >
          {STATUS_GLYPH[status]}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The activity's duration bar: a type-colored strip hanging off the spine
 * circle, its length the event's duration at the current journal zoom. Its
 * color matches the circle exactly (same TYPE_TOKENS accent), so it reads as
 * the card's own presence extending down the timeline. In-flow, so it grows the
 * row when long — the visible "this runs a while" cue. When it runs far enough
 * that the card is offscreen (a multi-day leg), its tail carries a scroll-back
 * button (the planner's affordance).
 */
export function DurationBar({
  kind,
  minutes,
  pxPerMinute,
  nodeId,
  discarded = false,
}: {
  kind: CardKind;
  minutes: number;
  pxPerMinute: number;
  /** The card this bar belongs to — the scroll-back target on long bars. */
  nodeId?: string;
  discarded?: boolean;
}) {
  const accent = TYPE_TOKENS[kind].accent;
  const height = journalBarHeight(minutes, pxPerMinute);
  const capped = minutes * pxPerMinute > JOURNAL_BAR_MAX_PX;
  const showScrollBack = Boolean(nodeId) && height >= JOURNAL_BAR_SCROLLBACK_PX;

  const scrollBack = () => {
    if (typeof document === "undefined" || !nodeId) return;
    const card = document.querySelector<HTMLElement>(
      `[data-node-id="${nodeId}"]`,
    );
    if (card && typeof card.scrollIntoView === "function") {
      card.scrollIntoView({
        behavior: scrollBehaviorFor(prefersReducedMotion()),
        block: "start",
      });
    }
  };

  return (
    <span
      data-testid="journal-duration-bar"
      data-kind={kind}
      data-minutes={minutes}
      className={[
        "relative mt-1 flex flex-col items-center",
        discarded ? "opacity-40 grayscale" : "",
      ].join(" ")}
      style={{ height }}
      title={`runs ${formatBarLabel(minutes)}`}
    >
      {/* The bar itself — a soft wash over the spine line, so the continuous
          line still reads beneath it. */}
      <span
        aria-hidden
        className="w-full flex-1 rounded-full"
        style={{
          width: JOURNAL_BAR_WIDTH_PX,
          backgroundColor: accent,
          opacity: 0.5,
          // A capped bar frays into a dashed tail to say "and then some".
          ...(capped
            ? {
                maskImage:
                  "linear-gradient(180deg, #000 78%, rgba(0,0,0,0.25) 100%)",
                WebkitMaskImage:
                  "linear-gradient(180deg, #000 78%, rgba(0,0,0,0.25) 100%)",
              }
            : {}),
        }}
      />
      {/* Scroll back up to the card — for bars long enough that the card has
          left the screen (a multi-day span). */}
      {showScrollBack ? (
        <button
          type="button"
          data-testid="journal-bar-scrollback"
          onClick={(e) => {
            e.stopPropagation();
            scrollBack();
          }}
          title="Back to the card"
          aria-label="Scroll back to the card"
          className="-mt-1 flex h-5 w-5 items-center justify-center rounded-full border border-ink/15 bg-paper text-ink/70 shadow-xs transition-colors hover:bg-ink hover:text-paper"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="block">
            <path
              d="M5 2.5 L1.8 6 M5 2.5 L8.2 6 M5 2.5 L5 8"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        </button>
      ) : null}
    </span>
  );
}

/** Compact "2h 30m" / "45m" duration label for the bar's tooltip. */
function formatBarLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

/** The small hollow circle a virtual (quiet) node sits on. */
export function QuietCircle() {
  return (
    <span
      aria-hidden
      className="relative z-10 block h-3 w-3 rounded-full border border-ink/30 bg-paper"
    />
  );
}

/**
 * The night treatment: now that the crisp colored bar belongs to activities,
 * evening reads as light fading rather than a bar. A soft dusk→night WASH fills
 * the gutter (the same sun palette the horizontal axis samples, evening→night
 * hours) with a whispered ☾ tick and caption beside it — atmosphere, not a
 * shape that competes with the duration bars. When the graph models the night
 * (a `night_bar` node, usually the hotel stay) its title names the stop.
 */
export function NightSegment({ title }: { title?: string | undefined }) {
  // Dusk (~19:00) melting into deep night (~23:30) — sampled from the shared
  // sun stops so the Journal and the planner's axis speak the same sky.
  const wash = `linear-gradient(180deg, ${sunColorAtHour(18.5)} 0%, ${sunColorAtHour(20.5)} 45%, ${sunColorAtHour(23.5)} 100%)`;
  return (
    <div
      data-testid="journal-night"
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-stretch gap-x-4"
      style={{ "--spine-col": `${SPINE_COL_PX}px` } as React.CSSProperties}
    >
      {/* The wash spans the whole gutter width (a fading sky), blurred at its
          edges so it never reads as a crisp bar. The ☾ tick rides the top. It
          sits BEHIND the timeline lines (`-z-10`) so the spine and a packaged
          journey's thread read unbroken THROUGH the night — atmosphere behind
          the line, never a break across it. The day section isolates its
          stacking context, so this negative layer stays above the page. */}
      <div className="relative flex justify-center py-1">
        <span
          aria-hidden
          data-testid="journal-night-wash"
          className="relative -z-10 flex h-14 w-full items-start justify-center rounded-md pt-1"
          style={{
            backgroundImage: wash,
            opacity: 0.5,
            maskImage:
              "radial-gradient(120% 100% at 50% 0%, #000 55%, transparent 100%)",
            WebkitMaskImage:
              "radial-gradient(120% 100% at 50% 0%, #000 55%, transparent 100%)",
          }}
        >
          <span className="text-[10px] leading-none text-paper/90">☾</span>
        </span>
      </div>
      <p className="flex items-center font-serif text-[12px] italic text-ink/40">
        {title ? `Night · ${title}` : "Night"}
      </p>
    </div>
  );
}
