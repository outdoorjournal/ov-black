"use client";

// The very-large viewport tier (Tailwind `2xl`, ≥1536px) — where the Journal's
// right region is wide enough to promote from the cockpit rail to the full
// inline detail (rail redesign, phase 4). SSR-safe (false until mounted so the
// server render matches) and reactive to viewport resizes. Mirrors the guarded
// matchMedia idiom already used in JournalView's onActivate so tests (no jsdom
// matchMedia) resolve to false and keep the cockpit-tier behaviour.

import { useEffect, useState } from "react";

const QUERY = "(min-width: 1536px)";

export function useIs2xl(): boolean {
  const [is2xl, setIs2xl] = useState(false);
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }
    const mql = window.matchMedia(QUERY);
    const sync = () => setIs2xl(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, []);
  return is2xl;
}
