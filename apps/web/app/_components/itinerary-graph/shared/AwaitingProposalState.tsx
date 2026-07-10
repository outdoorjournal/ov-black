"use client";

// Teaser empty state for a traveler viewing an advisor-crafted trip that has
// nothing published yet. The advisor builds privately in their workspace and
// content only reaches this official version when they publish — so instead
// of the self-serve builder prompt (BuilderEmptyState), the empty canvas says
// something is being made for them. Deliberately unhurried: the product is
// anti-instant, and anticipation is part of the service. Purely
// presentational; pointer events fall through to the board underneath.

import { Feather } from "lucide-react";

export function AwaitingProposalState() {
  return (
    <div
      data-testid="awaiting-proposal"
      className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-8"
    >
      <div className="max-w-sm text-center">
        <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full border border-ink/15 bg-white text-brand">
          <Feather className="h-5 w-5" />
        </span>
        <h2 className="mt-5 font-serif text-2xl leading-snug tracking-tight text-ink">
          Your advisor is crafting something
        </h2>
        <p className="mt-3 font-sans text-sm leading-relaxed text-ink/60">
          This trip is being composed for you by hand. When the first cut is
          ready it will appear here — every card yours to review, question,
          and approve.
        </p>
        <p className="mt-4 font-sans text-[11px] uppercase tracking-eyebrow text-ink/45">
          The concierge can pass along anything in the meantime
        </p>
      </div>
    </div>
  );
}
