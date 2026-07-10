"use client";

// The Journal's more-below cue (traveler-journal design, phase 5): when the
// journey's tail is off-screen, a soft bottom scroll shadow plus a quiet
// "↓ N more days" pill that jumps to the first off-screen day. The counting
// is the pure `tailBelow` helper (dayRailModel.ts); this component only measures —
// reads happen inside one rAF per scroll tick (no layout thrash), and the
// jump honours `prefers-reduced-motion` (instant instead of smooth).

import {
  useCallback,
  useEffect,
  useState,
  type RefObject,
} from "react";

import { itineraryGraphStore } from "../../store/itineraryGraphStore";

import { tailBelow, type TailProbe } from "./dayRailModel";
import { prefersReducedMotion, scrollBehaviorFor } from "./motion";
import type { Journal } from "./toJournal";

const SECTION_SELECTOR =
  '[data-testid="journal-day"], [data-testid="journal-elision"]';

export function MoreBelowCue({
  journal,
  scrollRootRef,
}: {
  /** Only read to re-measure when the derivation changes shape. */
  journal: Journal;
  scrollRootRef?: RefObject<HTMLElement | null> | undefined;
}) {
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  const [tail, setTail] = useState<{ days: number; date: string | null }>({
    days: 0,
    date: null,
  });

  const measure = useCallback(() => {
    const root = scrollRootRef?.current ?? null;
    const bottom = root
      ? root.getBoundingClientRect().bottom
      : window.innerHeight;
    const probes: TailProbe[] = Array.from(
      (root ?? document).querySelectorAll<HTMLElement>(SECTION_SELECTOR),
    ).map((el) => ({
      top: el.getBoundingClientRect().top,
      days: Number(el.dataset["dayCount"] ?? "1") || 1,
      date: el.dataset["date"] ?? el.dataset["startDate"] ?? null,
    }));
    const next = tailBelow(probes, bottom);
    setTail((prev) =>
      prev.days === next.days && prev.date === next.date ? prev : next,
    );
  }, [scrollRootRef]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const root = scrollRootRef?.current ?? null;
    const target: EventTarget = root ?? window;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        measure();
      });
    };
    measure();
    target.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      target.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
    // journal: re-measure when the derived sections change shape.
  }, [measure, scrollRootRef, journal]);

  if (cinemaMode || tail.days === 0) return null;

  const jump = () => {
    if (!tail.date) return;
    const scope: ParentNode = scrollRootRef?.current ?? document;
    const el = scope.querySelector<HTMLElement>(
      `[data-testid="journal-day"][data-date="${tail.date}"], [data-testid="journal-elision"][data-start-date="${tail.date}"]`,
    );
    if (!el || typeof el.scrollIntoView !== "function") return;
    el.scrollIntoView({
      behavior: scrollBehaviorFor(prefersReducedMotion()),
      block: "start",
    });
  };

  return (
    <>
      {/* The bottom scroll shadow — a whisper that the story continues. */}
      <div
        aria-hidden
        data-testid="journal-more-shadow"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-20 h-14 bg-linear-to-t from-ink/10 to-transparent"
      />
      {/* The jump pill — above the mobile day rail; tucked low on desktop. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-14 z-30 flex justify-center lg:bottom-5">
        <button
          type="button"
          data-testid="journal-more-below"
          onClick={jump}
          className="pointer-events-auto rounded-full border border-ink/15 bg-paper/90 px-3.5 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/60 shadow-sm backdrop-blur-sm transition-colors hover:border-ink/35 hover:text-ink"
        >
          ↓ {tail.days} more day{tail.days === 1 ? "" : "s"}
        </button>
      </div>
    </>
  );
}
