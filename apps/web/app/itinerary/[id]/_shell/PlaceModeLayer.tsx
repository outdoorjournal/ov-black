"use client";

// Place mode's cross-surface chrome (M006/PS5). Place mode is a LAYER, not a
// route (design §7): the held card floats over whatever's underneath, so this
// lives at the shell — above every planning destination — reading the transient
// `heldItem` / `lastPlacement` slices off the shared store.
//
// Three jobs:
//   1. While a card is held, show the floating HOLDING CHIP and, if we're not on
//      the Timeline (the only surface with slots), slide over to it — the held
//      state survives the nav because the store is shell-hosted.
//   2. Esc cancels the hold (the card floats home to the Collection).
//   3. After a drop, show the undo TOAST ("Added to Tue 14:00 · Undo").

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

const TOAST_MS = 6000;

const hhmm = (minute: number): string => {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

export function PlaceModeLayer() {
  const router = useRouter();
  const pathname = usePathname();
  const { timeline } = useTimelineData();

  const heldItem = itineraryGraphStore.useStore((s) => s.heldItem);
  const lastPlacement = itineraryGraphStore.useStore((s) => s.lastPlacement);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const clearHeldItem = itineraryGraphStore.useStore((s) => s.clearHeldItem);
  const undoPlacement = itineraryGraphStore.useStore((s) => s.undoPlacement);
  const clearLastPlacement = itineraryGraphStore.useStore((s) => s.clearLastPlacement);

  // The Timeline is where the slots are — pick from anywhere, place there.
  const onTimeline = pathname?.endsWith("/timeline") ?? false;
  useEffect(() => {
    if (heldItem && !onTimeline) {
      router.push(`/itinerary/${itineraryId}/timeline`);
    }
  }, [heldItem, onTimeline, router, itineraryId]);

  // Esc floats the held card home.
  useEffect(() => {
    if (!heldItem) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearHeldItem();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [heldItem, clearHeldItem]);

  // The undo toast self-dismisses; a new hold or an undo clears it earlier.
  useEffect(() => {
    if (!lastPlacement) return;
    const t = setTimeout(() => clearLastPlacement(), TOAST_MS);
    return () => clearTimeout(t);
  }, [lastPlacement, clearLastPlacement]);

  return (
    <>
      {heldItem ? (
        <div
          data-testid="holding-chip"
          className="fixed inset-x-0 bottom-20 z-50 mx-auto flex w-fit max-w-[92vw] items-center gap-3 rounded-full border border-ink/15 bg-paper/95 px-4 py-2.5 shadow-lg backdrop-blur md:bottom-6"
          role="status"
        >
          <span className="font-sans text-[10px] uppercase tracking-[0.18em] text-ink/45">
            Placing
          </span>
          <span className="min-w-0 max-w-[40vw] truncate font-serif text-[14px] text-ink">
            {heldItem.title}
          </span>
          <span className="hidden font-sans text-[11px] text-ink/50 sm:inline">
            Tap a time on the timeline
          </span>
          <button
            type="button"
            onClick={clearHeldItem}
            data-testid="holding-cancel"
            className="shrink-0 rounded-full px-2 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55 transition-colors hover:bg-ink/5 hover:text-ink"
          >
            Cancel
          </button>
        </div>
      ) : lastPlacement ? (
        <div
          data-testid="place-toast"
          className="fixed inset-x-0 bottom-20 z-50 mx-auto flex w-fit max-w-[92vw] items-center gap-3 rounded-full border border-ink/15 bg-ink px-4 py-2.5 text-paper shadow-lg md:bottom-6"
          role="status"
        >
          <span className="min-w-0 max-w-[60vw] truncate font-serif text-[14px]">
            Added to {dayLabel(timeline.days, lastPlacement.dayKey)} ·{" "}
            {hhmm(lastPlacement.minute)}
          </span>
          <button
            type="button"
            onClick={undoPlacement}
            data-testid="place-undo"
            className="shrink-0 rounded-full border border-paper/40 px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors hover:bg-paper/15"
          >
            Undo
          </button>
        </div>
      ) : null}
    </>
  );
}

function dayLabel(
  days: ReadonlyArray<{ date: string; label: string }>,
  dayKey: string,
): string {
  return days.find((d) => d.date === dayKey)?.label ?? dayKey;
}
