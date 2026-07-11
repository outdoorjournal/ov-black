"use client";

// Drag-to-resize for the desktop concierge docks (the itinerary ConciergeColumn
// and the basecamp RightRailChat). Both are left-attached, fixed-width flex
// columns; this hook turns that width into a user-draggable, persisted value.
//
// The load-bearing detail is CLAMPING. A width saved on a wide monitor must
// never strand the drag handle (or crush the content beside it) when the same
// browser reopens on a narrower screen. So every width — hydrated from storage,
// dragged, or inherited across a window resize — is clamped against the LIVE
// viewport: it can never exceed `viewport - minContentWidth`, guaranteeing both
// the handle and a usable slice of content stay on screen. Shrinking the window
// re-clamps immediately (see the resize listener).
//
// Width is exposed as a number; callers apply it through a `--dock-w` CSS var so
// it only takes effect at the desktop breakpoint (below it the dock is a mobile
// overlay / bounded block with its own sizing).

import { useCallback, useEffect, useRef, useState } from "react";

export type ResizableDockOptions = {
  /** localStorage key the chosen width persists under. */
  storageKey: string;
  /** Width before any drag / with no stored value (matches the SSR fallback). */
  defaultWidth: number;
  /** Smallest the dock may be dragged. */
  minWidth: number;
  /** Content that must stay visible beside the dock — the real strand-guard. */
  minContentWidth: number;
  /** Optional hard ceiling, independent of the viewport-derived one. */
  maxWidth?: number;
};

function clampWidth(w: number, opts: ResizableDockOptions): number {
  const vw = typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerWidth;
  const ceil = Math.min(opts.maxWidth ?? Number.POSITIVE_INFINITY, vw - opts.minContentWidth);
  // On a viewport too small to honour minWidth, the ceiling wins so the dock
  // never grows past what leaves room for the handle + content.
  const floor = Math.min(opts.minWidth, ceil);
  return Math.max(floor, Math.min(w, ceil));
}

export function useResizableDock(opts: ResizableDockOptions) {
  const { storageKey, defaultWidth } = opts;
  const [width, setWidth] = useState(defaultWidth);
  const [isResizing, setIsResizing] = useState(false);

  // Latest options + committed width kept in refs so the drag listeners and the
  // mount-only window-resize listener always read current values without
  // re-subscribing every render.
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const widthRef = useRef(width);
  widthRef.current = width;

  // Hydrate from storage once, clamped to the current viewport.
  useEffect(() => {
    let stored = defaultWidth;
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw != null) {
        const n = Number.parseFloat(raw);
        if (Number.isFinite(n)) stored = n;
      }
    } catch {
      // Storage disabled (private mode) — the default is fine.
    }
    setWidth(clampWidth(stored, optsRef.current));
  }, [storageKey, defaultWidth]);

  // Re-clamp when the window shrinks: the "reopened on a smaller screen" case.
  useEffect(() => {
    const onResize = () => setWidth((w) => clampWidth(w, optsRef.current));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = widthRef.current;
    setIsResizing(true);

    // Both docks are left-attached: cursor moving right grows the dock.
    const onMove = (ev: PointerEvent) => {
      setWidth(clampWidth(startWidth + (ev.clientX - startX), optsRef.current));
    };
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setIsResizing(false);
      const final = clampWidth(startWidth + (ev.clientX - startX), optsRef.current);
      setWidth(final);
      widthRef.current = final;
      try {
        window.localStorage.setItem(optsRef.current.storageKey, String(Math.round(final)));
      } catch {
        // Storage disabled — the width still applies for this session.
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  return { width, isResizing, onPointerDown };
}
