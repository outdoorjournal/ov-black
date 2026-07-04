"use client";

// The mobile concierge as a drag-up bottom sheet — the pattern most map +
// assistant apps converge on (Google/Apple Maps, Arc). The timeline stays the
// hero; the concierge peeks at the bottom and the traveler drags it up to a
// full conversation. Three snap points: peek (handle only), half, full.
//
// Why a sheet and not a separate chat tab: the agent's proposals are cards
// that land on the *current timeline* (via the shared store's pendingProposals).
// A sheet keeps both in one context, and when a proposal arrives on another
// day the handle surfaces a one-tap jump to it.
//
// Drag is bound to the handle only (via dragControls) so it never fights the
// chat's own scroll. The wrapped ConciergeChat is the same component the
// desktop aside uses, so the conversation behaves identically.

import { animate, motion, useDragControls, useMotionValue } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";

import { ConciergeChat } from "../horizontal/ConciergeChat";

type Snap = "peek" | "half" | "full";

// Height of the handle that stays on-screen when peeked.
const PEEK_PX = 80;

interface ConciergeSheetProps {
  audience: "traveler" | "advisor";
  apiBaseUrl: string | null;
  accessToken: string | null;
  clientId: string | null;
  itineraryId: string;
  pendingCount: number;
  /** Set when a proposal landed on a day other than the one in view. */
  proposalHint: { dayIndex: number; label: string } | null;
  onJumpToProposal: () => void;
}

export function ConciergeSheet({
  audience,
  apiBaseUrl,
  accessToken,
  clientId,
  itineraryId,
  pendingCount,
  proposalHint,
  onJumpToProposal,
}: ConciergeSheetProps) {
  const [viewportH, setViewportH] = useState(800);
  const [snap, setSnap] = useState<Snap>("peek");
  const y = useMotionValue(2000); // start off-screen; settles to peek on mount
  const dragControls = useDragControls();
  const didInit = useRef(false);

  const sheetH = Math.round(viewportH * 0.92);

  // Translate-down distances for each snap point (y = sheetH - visibleHeight).
  const snapY = useMemo<Record<Snap, number>>(
    () => ({
      full: 0,
      half: Math.max(0, sheetH - Math.round(viewportH * 0.55)),
      peek: Math.max(0, sheetH - PEEK_PX),
    }),
    [sheetH, viewportH],
  );

  // Track the live viewport height (mobile chrome show/hide changes it).
  useEffect(() => {
    const measure = () => setViewportH(window.innerHeight);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // Drive y to the active snap point. First settle is instant (no slide from
  // the off-screen seed); subsequent changes spring.
  useEffect(() => {
    const target = snapY[snap];
    if (!didInit.current) {
      didInit.current = true;
      y.set(target);
      return;
    }
    const controls = animate(y, target, {
      type: "spring",
      stiffness: 520,
      damping: 50,
    });
    return controls.stop;
  }, [snap, snapY, y]);

  // On release, snap to the nearest point, biased by fling velocity.
  const settle = (velocity: number) => {
    const projected = y.get() + velocity * 0.08;
    let best: Snap = "peek";
    let bestDist = Infinity;
    for (const s of ["full", "half", "peek"] as const) {
      const dist = Math.abs(projected - snapY[s]);
      if (dist < bestDist) {
        bestDist = dist;
        best = s;
      }
    }
    setSnap(best);
  };

  return (
    <>
      {snap !== "peek" ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="fixed inset-0 z-40 bg-ink/30"
          onClick={() => setSnap("peek")}
          aria-hidden
        />
      ) : null}

      <motion.div
        className="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-2xl border-t border-ink/15 bg-paper shadow-[0_-18px_44px_-12px_rgba(0,0,0,0.4)]"
        style={{ y, height: sheetH }}
        drag="y"
        dragListener={false}
        dragControls={dragControls}
        dragConstraints={{ top: snapY.full, bottom: snapY.peek }}
        dragElastic={0.04}
        onDragEnd={(_event, info) => settle(info.velocity.y)}
      >
        {/* Handle: the only drag origin, and a tap-to-expand affordance. Acts
            as the sheet's header so ChatPanel's own header is suppressed. */}
        <div
          onPointerDown={(event) => dragControls.start(event)}
          onClick={() => setSnap((s) => (s === "peek" ? "half" : s))}
          className="shrink-0 cursor-grab touch-none select-none px-4 pb-2 pt-2.5 active:cursor-grabbing"
        >
          <div className="mx-auto h-1 w-10 rounded-full bg-ink/20" />
          <div className="mt-2 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
                Concierge
              </span>
              {pendingCount > 0 ? (
                <span className="rounded-full bg-ink px-1.5 py-0.5 text-[9px] font-medium leading-none text-paper">
                  {pendingCount}
                </span>
              ) : null}
            </div>
            {proposalHint ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onJumpToProposal();
                }}
                className="shrink-0 rounded-full border border-ink/25 px-2.5 py-0.5 text-[10px] tracking-wide text-ink/75 transition-colors hover:bg-ink/5"
              >
                Idea added to {proposalHint.label} →
              </button>
            ) : (
              <span className="truncate text-[11px] italic text-ink/45">
                {snap === "peek" ? "Tap to chat with your concierge" : "Ask for an idea…"}
              </span>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <ConciergeChat
            audience={audience}
            apiBaseUrl={apiBaseUrl}
            accessToken={accessToken}
            clientId={clientId}
            itineraryId={itineraryId}
            hydrateHistory
            hideHeader
          />
        </div>
      </motion.div>
    </>
  );
}
