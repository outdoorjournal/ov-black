"use client";

// Cinema mode (traveler-journal design, phase 5) — the Journal, played. A mode
// FLAG over the same DOM, never a view: chrome (the right rail, the day rail,
// the version chip, the more-below cues) fades out, the ambient layer goes
// full-bleed (AmbientLayer reads the same store flag), and a
// requestAnimationFrame scroll driver eases from node to node with a ~4s dwell
// at each. Cinema and diff mode are mutually exclusive (the store enforces it)
// and the Play affordance hides while comparing.
//
// Input discipline:
//   · wheel / touch / a non-Esc key → PAUSE (the reader took the wheel; a
//     quiet Resume affordance appears)
//   · tap/click anywhere (outside the overlay's own buttons) or Esc → EXIT
//   · `prefers-reduced-motion` → no autoscroll at all: the Play affordance
//     doesn't render, and the driver refuses to start (double-gated).
//
// Scroll discipline: the loop only WRITES scrollTop per frame; layout reads
// happen once per glide (when the next target is chosen), so there is no
// interleaved read/write thrash.

import { useEffect, useRef, useState, type RefObject } from "react";

import { itineraryGraphStore } from "../../store/itineraryGraphStore";

import { prefersReducedMotion } from "./motion";

/** How long the driver rests on each node. */
export const CINEMA_DWELL_MS = 4000;
/** Glide-time bounds — short hops stay unhurried, long jumps stay watchable. */
const GLIDE_MIN_MS = 700;
const GLIDE_MAX_MS = 2200;
/** Where a node settles in the viewport — inside the scroll-active band. */
const BAND_CENTER = 0.45;

const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

// ── The entry — a small quiet Play on the hero ────────────────────────────────
export function CinemaPlayButton() {
  const diffMode = itineraryGraphStore.useStore((s) => s.diffMode);
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const storeApi = itineraryGraphStore.useStoreApi();

  // Hidden while comparing (mutually exclusive modes), while already playing,
  // when there is nothing to play, and under reduced motion (the doc's rule:
  // reduced motion disables autoscroll — so the entry simply doesn't render).
  if (diffMode || cinemaMode || nodes.length === 0 || prefersReducedMotion()) {
    return null;
  }

  return (
    <button
      type="button"
      data-testid="journal-cinema-play"
      onClick={() => storeApi.getState().setCinemaMode(true)}
      className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-white/35 bg-black/20 px-3.5 py-1.5 font-sans text-[10px] uppercase tracking-[0.2em] text-white/85 backdrop-blur-sm transition-colors hover:border-white/60 hover:bg-black/30"
    >
      <span aria-hidden className="text-[8px] leading-none">
        ▶
      </span>
      Play
    </button>
  );
}

// ── The driver ────────────────────────────────────────────────────────────────
export function CinemaDriver({
  scrollRootRef,
}: {
  scrollRootRef?: RefObject<HTMLElement | null> | undefined;
}) {
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const resumeRef = useRef<(() => void) | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!cinemaMode) return;
    // Reduced motion means no autoscroll, full stop — if cinema was reached
    // anyway (the Play gate is per-render), leave immediately.
    if (prefersReducedMotion()) {
      storeApi.getState().setCinemaMode(false);
      return;
    }
    const root = scrollRootRef?.current ?? null;
    const scroller: HTMLElement = root ?? document.documentElement;
    const scope: ParentNode = root ?? document;
    const targets = Array.from(
      scope.querySelectorAll<HTMLElement>(
        '[data-testid="journal-node"], [data-testid="journal-ghost"]',
      ),
    );
    if (targets.length === 0) {
      storeApi.getState().setCinemaMode(false);
      return;
    }

    let disposed = false;
    let raf = 0;
    let idx = 0;
    let phase: "glide" | "dwell" = "glide";
    let phaseStart = 0;
    let glideFrom = 0;
    let glideTo = 0;
    let glideMs = GLIDE_MIN_MS;

    const exit = () => {
      if (!disposed) storeApi.getState().setCinemaMode(false);
    };

    // One layout read per glide: where does this node settle?
    const beginGlide = (now: number) => {
      const el = targets[idx];
      if (!el) {
        exit();
        return;
      }
      const rect = el.getBoundingClientRect();
      const rootTop = root ? root.getBoundingClientRect().top : 0;
      const viewportH = root ? root.clientHeight : window.innerHeight;
      glideFrom = scroller.scrollTop;
      glideTo = Math.max(
        0,
        glideFrom +
          (rect.top - rootTop) +
          rect.height / 2 -
          viewportH * BAND_CENTER,
      );
      glideMs = Math.min(
        GLIDE_MAX_MS,
        Math.max(GLIDE_MIN_MS, Math.abs(glideTo - glideFrom) * 1.2),
      );
      phase = "glide";
      phaseStart = now;
      // Keep the rail/ambient in step even where IntersectionObserver lags.
      const nodeId = el.dataset["nodeId"];
      if (nodeId) storeApi.getState().focusNode(nodeId, "scroll");
    };

    const step = (now: number) => {
      if (disposed) return;
      if (!pausedRef.current) {
        if (phase === "glide") {
          const t = glideMs > 0 ? Math.min(1, (now - phaseStart) / glideMs) : 1;
          scroller.scrollTop =
            glideFrom + (glideTo - glideFrom) * easeInOutCubic(t);
          if (t >= 1) {
            phase = "dwell";
            phaseStart = now;
          }
        } else if (now - phaseStart >= CINEMA_DWELL_MS) {
          idx += 1;
          if (idx >= targets.length) {
            exit();
            return;
          }
          beginGlide(now);
        }
      }
      raf = requestAnimationFrame(step);
    };

    const pause = () => {
      if (!pausedRef.current) {
        pausedRef.current = true;
        setPaused(true);
      }
    };
    resumeRef.current = () => {
      pausedRef.current = false;
      setPaused(false);
      // Re-aim: the reader may have scrolled somewhere else while paused.
      beginGlide(performance.now());
    };

    const onWheel = () => pause();
    const onTouchMove = () => pause();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") exit();
      else pause();
    };
    const onPointerDown = (e: PointerEvent) => {
      // The overlay's own buttons (Resume / Exit) handle themselves.
      if (
        overlayRef.current &&
        e.target instanceof Node &&
        overlayRef.current.contains(e.target)
      ) {
        return;
      }
      exit();
    };

    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);

    beginGlide(performance.now());
    raf = requestAnimationFrame(step);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
      resumeRef.current = null;
      pausedRef.current = false;
      setPaused(false);
    };
  }, [cinemaMode, scrollRootRef, storeApi]);

  if (!cinemaMode) return null;

  return (
    <div
      ref={overlayRef}
      data-testid="journal-cinema-overlay"
      className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2"
    >
      <div className="flex items-center gap-4 rounded-full border border-ink/15 bg-paper/90 px-4 py-1.5 shadow-sm backdrop-blur-sm">
        {paused ? (
          <button
            type="button"
            data-testid="journal-cinema-resume"
            onClick={() => resumeRef.current?.()}
            className="font-sans text-[10px] uppercase tracking-[0.18em] text-ink/70 transition-colors hover:text-ink"
          >
            ▶ Resume
          </button>
        ) : (
          <span className="font-serif text-[12px] italic text-ink/50">
            the journey, playing…
          </span>
        )}
        <button
          type="button"
          data-testid="journal-cinema-exit"
          onClick={() => storeApi.getState().setCinemaMode(false)}
          className="font-sans text-[10px] uppercase tracking-[0.18em] text-ink/50 transition-colors hover:text-ink"
        >
          Exit · Esc
        </button>
      </div>
    </div>
  );
}
