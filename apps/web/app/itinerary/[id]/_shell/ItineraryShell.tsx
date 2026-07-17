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
// There is no first-run intake gate anymore: a brief-less trip lands straight on
// the dashboard, where the goal + timing are captured edit-in-place over the hero
// (DashboardHero). The old full-page "What are we planning?" ItineraryIntake is
// retired for every viewer — travelers get the immersive /new experience, advisors
// edit in place.

import { useState } from "react";

import type { DisplayStatus, GraphFindingResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/horizontalTypes";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { DockResizeHandle } from "@/app/_components/DockResizeHandle";
import { useResizableDock } from "@/lib/useResizableDock";
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
  status: DisplayStatus;
  role: UserRole;
  apiBaseUrl: string | null;
  accessToken: string | null;
  viewerOpenForkId: string | null;
  /** Traveler on an advisor-crafted trunk with nothing published yet (teaser). */
  awaitingProposal?: boolean;
  /** Per-currency plan price from the graph read (ADV-10) — `{}` when unpriced. */
  totals?: Record<string, string>;
  /** Kernel feasibility findings from the graph read (Phase 5) — seed the
   *  store's problem treatment on load. */
  graphFindings?: GraphFindingResponse[];
  /** 0048: traveler's preferred display currency + converted grand total. */
  displayCurrency?: string | null;
  totalDisplay?: string | null;
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
  awaitingProposal = false,
  totals = {},
  graphFindings = [],
  displayCurrency = null,
  totalDisplay = null,
  children,
}: ItineraryShellProps) {
  // <1100px the concierge is a summonable overlay (opened from the Rail on a
  // tablet, or the Chat tab on a phone); ≥1100px it is an in-flow column.
  const [conciergeOpen, setConciergeOpen] = useState(false);
  // Q5 (PS6): ≥1100px the concierge is open by default but collapsible to a slim
  // edge tab, so the planning space can take the full width when wanted.
  const [conciergeCollapsed, setConciergeCollapsed] = useState(false);
  // Bumped on every openConcierge() so the column can flash Artemis even when the
  // panel was already open (a summon that changes no layout still needs a cue).
  const [conciergeNudge, setConciergeNudge] = useState(0);
  // Drag-to-resize the ≥1100px in-flow concierge; persisted + viewport-clamped.
  const dock = useResizableDock({
    storageKey: "ovb.dock.itinerary",
    defaultWidth: 380,
    minWidth: 300,
    minContentWidth: 440,
    maxWidth: 680,
  });
  // The card composer (ADV-4) is summoned from the Studio button, the Collection
  // add affordance, or an empty timeline slot; a null prefill = compose into the
  // Collection, a {dayKey, minute} prefill = schedule at that slot.
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerPrefill, setComposerPrefill] = useState<ComposerPrefill>(null);

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
        awaitingProposal,
        totals,
        graphFindings,
        displayCurrency,
        totalDisplay,
      }}
    >
      <TimelineDataProvider value={{ timeline, baselineTitle }}>
        <ConciergeControlProvider
          value={{
            openConcierge: () => {
              // <1100px: reveal the summoned overlay. ≥1100px: the overlay flag
              // is inert, but if the in-flow column was collapsed to its edge
              // tab, un-collapse it — otherwise "open" would be a silent no-op.
              setConciergeOpen(true);
              setConciergeCollapsed(false);
              // Always flash Artemis, so a summon into an already-open panel
              // still registers visually.
              setConciergeNudge((n) => n + 1);
            },
            nudge: conciergeNudge,
          }}
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
              style={{ "--dock-w": `${dock.width}px` } as React.CSSProperties}
              className={[
                "flex-col bg-paper",
                conciergeCollapsed
                  ? "min-[1100px]:hidden"
                  : "min-[1100px]:flex min-[1100px]:w-[var(--dock-w,380px)] min-[1100px]:shrink-0 min-[1100px]:border-r min-[1100px]:border-ink/10",
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

            {/* Drag handle on the concierge's right edge (≥1100px, expanded only). */}
            {!conciergeCollapsed ? (
              <DockResizeHandle
                onPointerDown={dock.onPointerDown}
                active={dock.isResizing}
                className="hidden min-[1100px]:flex"
              />
            ) : null}

            {/* Reopen tab — only when the ≥1100px column is collapsed. A slim
                left-edge affordance so the concierge is one click from back. */}
            {conciergeCollapsed ? (
              <button
                type="button"
                onClick={() => setConciergeCollapsed(false)}
                data-testid="concierge-reopen"
                aria-label="Reopen the concierge"
                className="hidden shrink-0 items-center border-r border-brand/20 bg-brand/10 px-1.5 font-sans text-[9px] uppercase tracking-[0.16em] text-brand transition-colors hover:bg-brand/20 min-[1100px]:flex"
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
