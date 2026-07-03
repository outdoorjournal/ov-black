"use client";

// Agent-onboarding empty state for the builder. Once the brief is set but the
// timeline is still empty, a bare canvas doesn't tell you what to do — so we
// explain that the concierge builds the trip out, and point at where the
// conversation lives (the Concierge aside on desktop, the drag-up sheet on
// mobile). Purely presentational; it renders over the empty canvas and lets
// pointer events fall through to the board underneath.

import { Sparkles } from "lucide-react";

export type BuilderEmptyStateProps = {
  /** Where the concierge lives on this layout, so the hint points the right way. */
  hint: "aside" | "sheet";
};

export function BuilderEmptyState({ hint }: BuilderEmptyStateProps) {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full border border-ink/15 bg-white text-brand">
          <Sparkles className="h-5 w-5" />
        </span>
        <h2 className="mt-5 font-serif text-2xl leading-snug tracking-tight text-ink">
          A blank canvas, ready when you are
        </h2>
        <p className="mt-3 font-sans text-sm leading-relaxed text-ink/60">
          Tell the concierge what you have in mind — “a boutique hotel on
          Santorini,” “a day sailing the Cyclades” — and it proposes options
          right here for you to arrange into days.
        </p>
        <p className="mt-4 font-sans text-[11px] uppercase tracking-eyebrow text-ink/45">
          {hint === "aside"
            ? "Start in the Concierge panel →"
            : "↓ Open the concierge to begin"}
        </p>
      </div>
    </div>
  );
}
