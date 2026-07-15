"use client";

// The drawer itself — one panel, many typed payloads.
//
// Renders as a FLYOUT anchored to the host's chat window: the host passes a
// ref to its chat container and which `side` the panel should emerge from,
// and the panel slides out from under that edge — never covering the chat,
// layered above whatever sits beside it. The illusion is built with a
// portal + a viewport-fixed clip box that starts exactly at the chat's edge:
// the panel animates within the clip, so it appears from "underneath" the
// chat window regardless of any ancestor overflow-hidden or z-index.
//
// One surface at a time: a new one replaces the current, matching the
// correspondence pacing — the concierge lays one thing on the table.
// Escape or the close affordance dismisses.

import { X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

import { ArticleSurface } from "./ArticleSurface";
import { OptionsSurface } from "./OptionsSurface";
import { PlaceSurface } from "./PlaceSurface";
import { RouteSurface } from "./RouteSurface";
import type { ActiveSurface, ArticleSurfaceView, OptionView } from "./types";

export type AgentSurfaceProps = {
  surface: ActiveSurface | null;
  busy: boolean;
  onClose: () => void;
  onChooseOption: (option: OptionView) => void;
  /**
   * Persist an article surface's piece into the Collection. Optional: hosts
   * without a reading list (e.g. the itinerary shell) simply don't pass it,
   * and an article surface there falls back to a read-only link.
   */
  onAddToReadingList?: (article: ArticleSurfaceView) => Promise<boolean>;
  /** The chat window the panel slides out from (measured, not re-parented). */
  anchorRef: RefObject<HTMLElement | null>;
  /**
   * Optional taller element the panel's vertical extent matches. The slide
   * edge stays at anchorRef; top/height come from here — for hosts whose chat
   * window starts partway down a full-height column (basecamp first touch).
   */
  verticalAnchorRef?: RefObject<HTMLElement | null>;
  /** Which side of the chat window the panel emerges toward. */
  side: "left" | "right";
};

const KIND_LABEL: Record<ActiveSurface["kind"], string> = {
  place: "Place brief",
  route: "The route",
  options: "A decision",
  article: "A read",
};

const PANEL_MAX_WIDTH = 420;
const PANEL_MIN_WIDTH = 300;
const VIEWPORT_MARGIN = 16;

type FlyoutBox = { top: number; left: number; width: number; height: number };

function surfaceKey(surface: ActiveSurface): string {
  if (surface.kind === "place") return `place:${surface.query}`;
  return `${surface.kind}:${surface.surfaceId}`;
}

function measureFlyout(
  anchor: HTMLElement,
  side: "left" | "right",
  verticalAnchor?: HTMLElement | null,
): FlyoutBox {
  const rect = anchor.getBoundingClientRect();
  const vRect = verticalAnchor ? verticalAnchor.getBoundingClientRect() : rect;
  if (side === "right") {
    const available = window.innerWidth - rect.right - VIEWPORT_MARGIN;
    const width = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, available));
    // When the viewport is too tight, pull the box left so it stays on
    // screen — the panel then overlaps the chat's edge rather than clipping.
    const left = Math.min(rect.right, window.innerWidth - VIEWPORT_MARGIN - width);
    return { top: vRect.top, left, width, height: vRect.height };
  }
  const available = rect.left - VIEWPORT_MARGIN;
  const width = Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, available));
  const left = Math.max(rect.left - width, VIEWPORT_MARGIN);
  return { top: vRect.top, left, width, height: vRect.height };
}

export function AgentSurface({
  surface,
  busy,
  onClose,
  onChooseOption,
  onAddToReadingList,
  anchorRef,
  verticalAnchorRef,
  side,
}: AgentSurfaceProps) {
  // Portals need a browser; render nothing during SSR/hydration.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // The clip box beside the chat window. Kept in state (not nulled on close)
  // so the exit slide still has geometry to animate within.
  const [box, setBox] = useState<FlyoutBox | null>(null);

  useLayoutEffect(() => {
    if (!surface) return;
    const measure = () => {
      const anchor = anchorRef.current;
      if (anchor) setBox(measureFlyout(anchor, side, verticalAnchorRef?.current));
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [surface, side, anchorRef, verticalAnchorRef]);

  useEffect(() => {
    if (!surface) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [surface, onClose]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {surface && box ? (
        <motion.div
          key={surfaceKey(surface)}
          data-testid="agent-surface-flyout"
          initial="closed"
          animate="open"
          exit="closed"
          className="pointer-events-none fixed z-40 overflow-hidden"
          style={{ top: box.top, left: box.left, width: box.width, height: box.height }}
        >
          <motion.section
            role="complementary"
            aria-label={KIND_LABEL[surface.kind]}
            data-testid="agent-surface"
            data-surface-kind={surface.kind}
            variants={{
              open: { x: 0 },
              closed: { x: side === "right" ? "-100%" : "100%" },
            }}
            transition={{ duration: 0.26, ease: "easeOut" }}
            className={cn(
              "pointer-events-auto relative flex h-full w-full flex-col bg-paper shadow-float",
              "ring-1 ring-ink/10",
              side === "right" ? "rounded-r-md" : "rounded-l-md",
            )}
          >
            {/* The seam: the chat window's edge casts a shadow onto the panel,
                selling the slide-out-from-underneath. */}
            <div
              aria-hidden
              className={cn(
                "pointer-events-none absolute inset-y-0 z-10 w-3",
                side === "right"
                  ? "left-0 bg-gradient-to-r from-ink/20 to-transparent"
                  : "right-0 bg-gradient-to-l from-ink/20 to-transparent",
              )}
            />
            <header className="flex items-center justify-between border-b border-ink/10 px-6 py-3">
              <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-ink/45">
                {KIND_LABEL[surface.kind]}
              </p>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close panel"
                data-testid="agent-surface-close"
                className="rounded-full p-1 text-ink/45 transition-colors hover:bg-ink/6 hover:text-ink"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {surface.kind === "place" ? (
                <PlaceSurface label={surface.label} query={surface.query} />
              ) : surface.kind === "route" ? (
                <RouteSurface route={surface.route} />
              ) : surface.kind === "article" ? (
                <ArticleSurface
                  article={surface.article}
                  alreadySaved={surface.alreadySaved ?? false}
                  onAdd={
                    onAddToReadingList ??
                    (async () => false)
                  }
                />
              ) : (
                <OptionsSurface options={surface.options} busy={busy} onChoose={onChooseOption} />
              )}
            </div>
          </motion.section>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
