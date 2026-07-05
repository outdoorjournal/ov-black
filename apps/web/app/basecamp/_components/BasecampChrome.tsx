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
// traveler self-serve "start a new itinerary" CTA lives with the "Your
// itineraries" surface (ItineraryGrid / EmptyItinerariesHint), not the masthead.

import type { ReactNode } from "react";

import { AppHeader } from "@/app/_components/app-header/AppHeader";
import type { AppHeaderUser } from "@/lib/appHeader";

import { BasecampRail } from "./BasecampRail";

export type BasecampChromeProps = {
  user: AppHeaderUser;
  children: ReactNode;
};

export function BasecampChrome({ user, children }: BasecampChromeProps) {
  return (
    <main className="relative flex min-h-screen flex-col bg-paper text-ink">
      <AppHeader user={user} homeHref="/basecamp" />

      {/* Same shape as the itinerary shell: the shared rail on the left, the
          surface (which may lead with the concierge) filling the rest. */}
      <div className="flex min-h-0 flex-1">
        <BasecampRail />
        <section className="relative z-10 min-w-0 flex-1">{children}</section>
      </div>
    </main>
  );
}
