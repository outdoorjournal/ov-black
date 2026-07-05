// The shared shell for /basecamp — the client's persistent home.
//
// Light editorial treatment: a warm paper frame with crisp ink type and a
// single orange accent, matching the client-facing direction. The immersive
// "dark chat" lives inside the children (AtmosFrame in SinglePromptCard's
// engaged view, and the frosted RightRailChat) — those own their own dark
// mood surfaces, so the shell stays light around them.
//
// The masthead is the SAME shared AppHeader the itinerary + command-center
// surfaces use (M006/PS7) — basecamp no longer carries a bespoke header. The
// traveler self-serve "start a new itinerary" CTA rides the header's secondary
// slot so it stays available within the shared nav.

import type { ReactNode } from "react";

import { AppHeader } from "@/app/_components/app-header/AppHeader";
import { startNewItinerary } from "@/app/_actions/start-itinerary";
import type { AppHeaderUser } from "@/lib/appHeader";

export type BasecampChromeProps = {
  user: AppHeaderUser;
  children: ReactNode;
};

export function BasecampChrome({ user, children }: BasecampChromeProps) {
  return (
    <main className="relative min-h-screen bg-paper text-ink">
      <AppHeader
        user={user}
        homeHref="/basecamp"
        secondary={
          <div className="flex justify-end border-t border-paper/10 px-6 py-2 sm:px-10">
            {/* Traveler self-serve entry point: create a trip and land in the
                builder's first-run intake. */}
            <form action={startNewItinerary}>
              <button
                type="submit"
                className="rounded-full border border-paper/30 px-4 py-1.5 text-[11px] uppercase tracking-label text-paper/80 transition-colors hover:border-brand hover:text-paper"
              >
                Start a new itinerary
              </button>
            </form>
          </div>
        }
      />

      <section className="relative z-10">{children}</section>
    </main>
  );
}
