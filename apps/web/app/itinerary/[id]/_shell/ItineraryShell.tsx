"use client";

// The planner shell (M006/PS1). This is the ONE client boundary the routed
// itinerary lives inside: it owns the graph store Provider + the server-fresh
// timeline context, and lays out the two axes around the routed planning space —
//   places (the Rail)  ·  people (the ConciergeColumn)  ·  the view (children).
//
// Why the shell (not the view) owns the Provider: the layout persists across
// navigation between the routed destinations (timeline / collection / studio),
// so the store — and the open concierge — survive a view switch instead of
// unmounting with the page. The `key={itineraryId}` in the layout gives each
// trip its own fresh store; sibling-route nav keeps the same instance.
//
// First-run intake still gates ahead of everything: a trip with no brief shows
// the intake and mounts neither the store nor the concierge until a goal exists
// (mirrors the retired ItineraryBuilderScreen).

import { useState } from "react";

import type { ItineraryStatus } from "@ov-black/api-client";

import { ItineraryIntake } from "@/app/_components/itinerary-graph/intake/ItineraryIntake";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/horizontalTypes";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import type { UserRole } from "@/lib/role";

import { CardComposer } from "./CardComposer";
import { ComposerControlProvider, type ComposerPrefill } from "./ComposerControl";
import { ConciergeColumn } from "./ConciergeColumn";
import { ConciergeControlProvider } from "./ConciergeControl";
import { MobileTabBar } from "./MobileTabBar";
import { PlaceModeLayer } from "./PlaceModeLayer";
import { Rail } from "./Rail";

export type ItineraryShellProps = {
  timeline: ItineraryTimeline;
  baselineTitle: string | null;
  itineraryId: string;
  status: ItineraryStatus;
  role: UserRole;
  apiBaseUrl: string | null;
  accessToken: string | null;
  viewerOpenForkId: string | null;
  /** True when the trip has no brief yet — gate on the first-run intake. */
  needsBrief: boolean;
  audience: "advisor" | "traveler";
  /** The active routed destination (timeline / collection / studio / …). */
  children: React.ReactNode;
};

export function ItineraryShell({
  timeline,
  baselineTitle,
  itineraryId,
  status,
  role,
  apiBaseUrl,
  accessToken,
  viewerOpenForkId,
  needsBrief,
  audience,
  children,
}: ItineraryShellProps) {
  const [showIntake, setShowIntake] = useState(needsBrief);
  // <1100px the concierge is a summonable overlay (opened from the Rail on a
  // tablet, or the Chat tab on a phone); ≥1100px it is an in-flow column.
  const [conciergeOpen, setConciergeOpen] = useState(false);
  // Q5 (PS6): ≥1100px the concierge is open by default but collapsible to a slim
  // edge tab, so the planning space can take the full width when wanted.
  const [conciergeCollapsed, setConciergeCollapsed] = useState(false);
  // The card composer (ADV-4) is summoned from the Studio button, the Collection
  // add affordance, or an empty timeline slot; a null prefill = compose into the
  // Collection, a {dayKey, minute} prefill = schedule at that slot.
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState<ComposerPrefill>(null);

  if (showIntake && apiBaseUrl && accessToken) {
    return (
      <ItineraryIntake
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
        audience={audience}
        onSaved={() => setShowIntake(false)}
        onSkip={() => setShowIntake(false)}
      />
    );
  }

  return (
    <itineraryGraphStore.Provider
      initial={{
        timeline,
        itineraryId,
        status,
        role,
        apiBaseUrl,
        accessToken,
        viewerOpenForkId,
      }}
    >
      <TimelineDataProvider value={{ timeline, baselineTitle }}>
        <ConciergeControlProvider
          value={{ openConcierge: () => setConciergeOpen(true) }}
        >
         <ComposerControlProvider
          value={{
            openComposer: (prefill) => {
              setComposerPrefill(prefill ?? null);
              setComposerOpen(true);
            },
          }}
         >
          <div
            data-testid="itinerary-shell"
            className="relative flex min-h-0 flex-1 overflow-hidden"
          >
            <Rail onOpenConcierge={() => setConciergeOpen(true)} />

            {/* People axis. ≥1100px: an in-flow column (collapsible to an edge
                tab — Q5). Below that: hidden until summoned, then a full-screen
                overlay (neutralised back to in-flow at ≥1100 so the state never
                traps the desktop layout). */}
            <aside
              data-testid="concierge-column"
              data-collapsed={conciergeCollapsed ? "true" : "false"}
              className={[
                "flex-col bg-paper",
                conciergeCollapsed
                  ? "min-[1100px]:hidden"
                  : "min-[1100px]:flex min-[1100px]:w-[380px] min-[1100px]:shrink-0 min-[1100px]:border-r min-[1100px]:border-ink/10",
                conciergeOpen
                  ? "fixed inset-0 z-40 flex min-[1100px]:static min-[1100px]:inset-auto min-[1100px]:z-auto"
                  : "hidden",
              ].join(" ")}
            >
              <ConciergeColumn
                onClose={() => setConciergeOpen(false)}
                onCollapse={() => setConciergeCollapsed(true)}
              />
            </aside>

            {/* Reopen tab — only when the ≥1100px column is collapsed. A slim
                left-edge affordance so the concierge is one click from back. */}
            {conciergeCollapsed ? (
              <button
                type="button"
                onClick={() => setConciergeCollapsed(false)}
                data-testid="concierge-reopen"
                aria-label="Reopen the concierge"
                className="hidden shrink-0 items-center border-r border-ink/10 bg-paper/85 px-1.5 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/50 transition-colors hover:bg-ink/5 hover:text-ink min-[1100px]:flex"
              >
                <span className="[writing-mode:vertical-rl] rotate-180">Concierge ›</span>
              </button>
            ) : null}

            {/* Planning space — the routed destination fills the rest. The
                padding clears the fixed mobile tab bar (h-14); none on md+. */}
            <main
              data-testid="planning-space"
              className="relative flex min-w-0 flex-1 flex-col pb-14 md:pb-0"
            >
              {children}
            </main>

            <MobileTabBar onOpenConcierge={() => setConciergeOpen(true)} />

            {/* Place mode's cross-surface chrome (PS5): the holding chip + undo
                toast float above every destination, driven by the shared store. */}
            <PlaceModeLayer />

            {/* Card composer (ADV-4): summoned over any destination. Inside the
                store Provider so it can author via the shared graph store. */}
            {composerOpen ? (
              <CardComposer
                prefill={composerPrefill}
                onClose={() => setComposerOpen(false)}
              />
            ) : null}
          </div>
         </ComposerControlProvider>
        </ConciergeControlProvider>
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}
