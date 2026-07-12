"use client";

// The Journal's scroll-active system. One IntersectionObserver watches every
// card row against a CENTER BAND of the scroll viewport (~35–55%); whichever
// card occupies the band most is the scroll-active node (focusSource:
// "scroll"). An explicit click PINS (focusSource: "click"); scroll observation
// leaves a pin alone until the pinned card exits the band entirely, at which
// point scroll resumes control — the "balance" rule made deterministic.
//
// A pin only yields to scroll when the USER actually scrolled the card out of
// the band — not when a PROGRAMMATIC reflow moves it there. Editing a card from
// the rail / inline detail (e.g. re-timing it) re-sorts the spine and can shove
// the pinned card out of the band with no scroll event; without this guard the
// observer would then hand focus to whatever card slid into the band, swapping
// the panel out from under an active edit. So we gate band-exit release on a
// real scroll having happened since the pin landed.

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
  // True once the user has scrolled since the current click-pin landed. A fresh
  // pin resets it to false (below); a real scroll event flips it true. The IO
  // release path reads it so a programmatic reflow can't masquerade as a scroll.
  const userScrolledSincePinRef = useRef(false);

  // A real scroll on the banded root (or the window) is the ONLY thing that
  // arms pin-release. Programmatic content moves don't fire 'scroll'.
  useEffect(() => {
    const root = scrollRootRef?.current ?? null;
    const target: Window | HTMLElement = root ?? window;
    const onScroll = () => {
      userScrolledSincePinRef.current = true;
    };
    target.addEventListener("scroll", onScroll, { passive: true });
    return () => target.removeEventListener("scroll", onScroll);
  }, [scrollRootRef]);

  // Reset the scroll gate whenever a fresh click-pin lands, so the pin holds
  // through any reflow until the user next scrolls it away themselves.
  useEffect(() => {
    return storeApi.subscribe((s, prev) => {
      const freshPin =
        s.focusSource === "click" &&
        s.focusedNodeId != null &&
        (s.focusedNodeId !== prev.focusedNodeId || prev.focusSource !== "click");
      if (freshPin) userScrolledSincePinRef.current = false;
    });
  }, [storeApi]);

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
        // A HARD lock (the 2xl inline detail is expanded) stands the observer
        // fully down — scrolling the timeline never swaps the locked card.
        if (s.focusLocked) return;
        // A click-pin holds while the pinned card is anywhere in the band, and
        // — even once it leaves — until the USER has scrolled since pinning. A
        // programmatic reflow (a re-time / edit from the rail) that shoves the
        // pinned card out of the band must not release the pin.
        if (s.focusSource === "click" && s.focusedNodeId) {
          const pinnedRatio = ratiosRef.current.get(s.focusedNodeId) ?? 0;
          if (pinnedRatio > 0) return;
          if (!userScrolledSincePinRef.current) return;
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
