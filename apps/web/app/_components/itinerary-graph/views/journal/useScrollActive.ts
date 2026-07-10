"use client";

// The Journal's scroll-active system. One IntersectionObserver watches every
// card row against a CENTER BAND of the scroll viewport (~35–55%); whichever
// card occupies the band most is the scroll-active node (focusSource:
// "scroll"). An explicit click PINS (focusSource: "click"); scroll observation
// leaves a pin alone until the pinned card exits the band entirely, at which
// point scroll resumes control — the "balance" rule made deterministic.

import { useCallback, useEffect, useRef, type RefCallback, type RefObject } from "react";

import { itineraryGraphStore } from "../../store/itineraryGraphStore";

// The band: everything outside viewport 35%–55% is trimmed from the IO root,
// so intersectionRatio measures "how much of this card is in the band".
const BAND_ROOT_MARGIN = "-35% 0px -45% 0px";
const THRESHOLDS = [0, 0.05, 0.15, 0.3, 0.5, 0.75, 1];

export function useScrollActive({
  scrollRootRef,
}: {
  /** The scrolling ancestor to band against; null/absent = the viewport. */
  scrollRootRef?: RefObject<HTMLElement | null> | undefined;
}): (nodeId: string) => RefCallback<HTMLElement> {
  const storeApi = itineraryGraphStore.useStoreApi();
  const observerRef = useRef<IntersectionObserver | null>(null);
  const elementsRef = useRef(new Map<string, HTMLElement>());
  const ratiosRef = useRef(new Map<string, number>());
  const idOfElement = useRef(new WeakMap<Element, string>());

  useEffect(() => {
    // jsdom (and very old browsers) lack IntersectionObserver — the Journal
    // then simply has no scroll-driven focus, which is a graceful floor.
    if (typeof IntersectionObserver === "undefined") return;
    const root = scrollRootRef?.current ?? null;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = idOfElement.current.get(entry.target);
          if (!id) continue;
          ratiosRef.current.set(
            id,
            entry.isIntersecting ? entry.intersectionRatio : 0,
          );
        }
        const s = storeApi.getState();
        // A click-pin holds while the pinned card is anywhere in the band.
        if (s.focusSource === "click" && s.focusedNodeId) {
          const pinnedRatio = ratiosRef.current.get(s.focusedNodeId) ?? 0;
          if (pinnedRatio > 0) return;
        }
        let bestId: string | null = null;
        let bestRatio = 0;
        for (const [id, ratio] of ratiosRef.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        }
        if (
          bestId &&
          (bestId !== s.focusedNodeId || s.focusSource !== "scroll")
        ) {
          s.focusNode(bestId, "scroll");
        }
      },
      { root, rootMargin: BAND_ROOT_MARGIN, threshold: THRESHOLDS },
    );
    observerRef.current = io;
    for (const el of elementsRef.current.values()) io.observe(el);
    return () => {
      io.disconnect();
      observerRef.current = null;
    };
  }, [scrollRootRef, storeApi]);

  // Stable per-id callback refs so React re-renders don't churn observation.
  const refsRef = useRef(new Map<string, RefCallback<HTMLElement>>());
  return useCallback(
    (nodeId: string): RefCallback<HTMLElement> => {
      const existing = refsRef.current.get(nodeId);
      if (existing) return existing;
      const cb: RefCallback<HTMLElement> = (el) => {
        const prev = elementsRef.current.get(nodeId);
        if (prev && prev !== el) observerRef.current?.unobserve(prev);
        if (el) {
          elementsRef.current.set(nodeId, el);
          idOfElement.current.set(el, nodeId);
          observerRef.current?.observe(el);
        } else {
          elementsRef.current.delete(nodeId);
          ratiosRef.current.delete(nodeId);
        }
      };
      refsRef.current.set(nodeId, cb);
      return cb;
    },
    [],
  );
}
