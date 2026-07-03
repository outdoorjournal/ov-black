// The shared shell for /basecamp — the client's persistent home.
//
// Light editorial treatment: a warm paper frame with crisp ink type and a
// single orange accent, matching the client-facing direction. The immersive
// "dark chat" lives inside the children (AtmosFrame in SinglePromptCard's
// engaged view, and the frosted RightRailChat) — those own their own dark
// mood surfaces, so the shell stays light around them.

import type { ReactNode } from "react";

import { signOutAction } from "@/app/_actions/sign-out";
import { startNewItinerary } from "@/app/_actions/start-itinerary";

export type BasecampChromeProps = {
  children: ReactNode;
};

export function BasecampChrome({ children }: BasecampChromeProps) {
  return (
    <main className="relative min-h-screen bg-paper text-ink">
      <header className="relative z-10 flex items-center justify-between px-6 py-6 sm:px-10">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-2xl tracking-tight">
            Outdoor Voyage
          </span>
          <span className="text-[10px] uppercase tracking-eyebrow text-ink/50">
            Black
          </span>
        </div>
        <div className="flex items-center gap-5">
          {/* Traveler self-serve entry point: create a trip and land in the
              builder's first-run intake. */}
          <form action={startNewItinerary}>
            <button
              type="submit"
              className="rounded-full border border-ink/20 px-4 py-1.5 text-[11px] uppercase tracking-label text-ink/70 transition-colors hover:border-brand hover:text-ink"
            >
              Start a new itinerary
            </button>
          </form>
          <form action={signOutAction}>
            <button
              type="submit"
              className="border-b border-transparent text-[10px] uppercase tracking-label text-ink/60 transition-colors hover:border-ink/60 hover:text-ink"
            >
              Sign out
            </button>
          </form>
        </div>
      </header>

      <section className="relative z-10">{children}</section>
    </main>
  );
}
