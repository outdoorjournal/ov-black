// The Journal's reduced-motion discipline (traveler-journal design, phase 5).
// Every piece of phase-5 motion — the ambient crossfade, day-rail jumps, the
// elision expand, cinema — routes through these helpers so the
// `prefers-reduced-motion` branches are pure and unit-testable:
//
//   crossfades → instant swaps · smooth scrolls → instant jumps · no
//   autoscroll (cinema's Play affordance simply doesn't render).
//
// Components animating with framer-motion use its reactive `useReducedMotion`
// hook and feed the boolean here; imperative call sites (scroll jumps, the
// Play gate) read `prefersReducedMotion()` at event/render time.

/** The ambient watermark's crossfade length (the design's 300–600ms band). */
export const AMBIENT_FADE_S = 0.45;

/** The elision marker's expand/collapse length. */
export const ELISION_EXPAND_S = 0.3;

/** OS-level reduced-motion, read at call time; false wherever unknowable. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Smooth scroll, unless motion is reduced — then an instant jump. */
export function scrollBehaviorFor(reduced: boolean): ScrollBehavior {
  return reduced ? "auto" : "smooth";
}

/** The ambient crossfade duration — an instant swap under reduced motion. */
export function ambientFadeSeconds(reduced: boolean): number {
  return reduced ? 0 : AMBIENT_FADE_S;
}

/** The elision expand duration — instant under reduced motion. */
export function elisionExpandSeconds(reduced: boolean): number {
  return reduced ? 0 : ELISION_EXPAND_S;
}
