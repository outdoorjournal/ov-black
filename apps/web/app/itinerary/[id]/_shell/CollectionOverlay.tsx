"use client";

// The Collection as a summonable LAYER over the timeline (M006/PS5→PS6). At xl+
// the Collection sits as a rail beside the timeline; in the md–xl band it isn't,
// so this floats it in on demand for pick-then-place without leaving the surface.
// Picking a card to place auto-closes the drawer so the timeline's tap targets
// are visible underneath. Below md, place mode is off (the Schedule button is
// desktop-only), so the summon hides there too.

import { DndContext } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";

import { CollectionRail } from "@/app/_components/itinerary-graph/collection/CollectionRail";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import { useOpenNode } from "./useOpenNode";

export function CollectionOverlay() {
  const [open, setOpen] = useState(false);
  const heldItem = itineraryGraphStore.useStore((s) => s.heldItem);
  const openNode = useOpenNode();
  const closeRef = useRef<HTMLButtonElement>(null);

  // Move focus into the drawer when it opens (keyboard users land inside, and
  // Esc / the backdrop / Close are all reachable from here).
  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  // Holding a card (from this drawer or the rail) closes it, revealing the slots.
  useEffect(() => {
    if (heldItem) setOpen(false);
  }, [heldItem]);

  // Esc closes the drawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {/* Summon — only in the md–xl band (below md place mode is off; at xl+ the
          rail is already beside the timeline), and never while a card is held. */}
      {!heldItem ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-testid="collection-summon"
          aria-label="Open the Collection"
          className="fixed bottom-6 right-6 z-30 hidden items-center gap-1.5 rounded-full border border-ink/15 bg-paper/95 px-4 py-2 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/70 shadow-md transition-colors hover:bg-ink hover:text-paper md:flex xl:hidden"
        >
          Collection
        </button>
      ) : null}

      {open ? (
        <div
          className="fixed inset-0 z-50 flex"
          role="dialog"
          aria-modal="true"
          aria-label="Collection"
        >
          <button
            type="button"
            aria-label="Close the Collection"
            data-testid="collection-overlay-backdrop"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-ink/30"
          />
          <div
            data-testid="collection-overlay"
            className="relative ml-auto flex h-full w-[380px] max-w-[88vw] flex-col bg-paper shadow-2xl"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-ink/10 px-3 py-2">
              <span className="font-sans text-[10px] uppercase tracking-[0.22em] text-ink/55">
                Collection
              </span>
              <button
                ref={closeRef}
                type="button"
                onClick={() => setOpen(false)}
                data-testid="collection-overlay-close"
                className="h-7 rounded-md px-2 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55 transition-colors hover:bg-ink/5 hover:text-ink"
              >
                Close
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <DndContext>
                <CollectionRail variant="overlay" onOpenNode={openNode} />
              </DndContext>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
