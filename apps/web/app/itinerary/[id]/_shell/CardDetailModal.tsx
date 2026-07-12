"use client";

// The card detail as a dismissible MODAL (rail redesign, phase 3). The full
// detail lives at /itinerary/[id]/item/[nodeId] as a real route; an intercepting
// parallel route ((.)item/[nodeId] in the @modal slot) renders THIS overlay when
// that URL is reached by a soft navigation from within the shell (a Journal card
// tap / "Open full →"), so it feels like a modal that dismisses — while a hard
// nav or refresh still lands on the full-page destination.
//
// Dismiss = router.back() (Escape, the backdrop, or the ✕) — which pops the
// intercepted URL and returns to the surface underneath (the Journal). Reuses
// the exact CardDetailView the destination renders, so the two never diverge.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { CardDetailView } from "./CardDetailView";

export function CardDetailModal({ nodeId }: { nodeId: string }) {
  const router = useRouter();

  // Escape dismisses; the browser Back button already does (it pops the
  // intercepted entry). Lock body scroll while the overlay is up.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") router.back();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [router]);

  return (
    <div
      data-testid="card-detail-modal"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) router.back();
      }}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 backdrop-blur-sm sm:p-8"
    >
      <div className="relative w-full max-w-5xl rounded-xl bg-paper shadow-2xl">
        <button
          type="button"
          onClick={() => router.back()}
          data-testid="card-detail-modal-close"
          aria-label="Close"
          className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-ink/5 font-sans text-ink/60 transition-colors hover:bg-ink/10 hover:text-ink"
        >
          ✕
        </button>
        <CardDetailView nodeId={nodeId} />
      </div>
    </div>
  );
}
