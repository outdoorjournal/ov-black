// Pure command-palette vocabulary (Wave F). The static navigation actions and
// their query filter live here — outside the client component — so the ranking
// is unit-testable and the palette component stays a thin cmdk shell.

import type { Route } from "next";

export type PaletteNavAction = {
  id: string;
  label: string;
  href: Route;
  /** Extra match terms beyond the label ("billing" finds Money). */
  keywords: readonly string[];
};

export const PALETTE_NAV_ACTIONS: readonly PaletteNavAction[] = [
  {
    id: "nav-ops",
    label: "Ops · Mission Control",
    href: "/command-center",
    keywords: ["home", "dashboard", "overview", "attention", "feed"],
  },
  {
    id: "nav-clients",
    label: "Clients",
    href: "/command-center/clients",
    keywords: ["roster", "people"],
  },
  {
    id: "nav-trips",
    label: "Trips",
    href: "/command-center/trips",
    keywords: ["itineraries", "travel", "journeys"],
  },
  {
    id: "nav-money",
    label: "Money",
    href: "/command-center/money",
    keywords: ["invoices", "billing", "payments", "outstanding"],
  },
  {
    id: "nav-new-client",
    label: "New client",
    href: "/command-center/new-client",
    keywords: ["add", "create", "invite", "onboard"],
  },
] as const;

/**
 * Filter the static nav actions against the palette query. Empty query shows
 * everything (the palette's resting state is a nav menu); otherwise match
 * case-insensitively on the label or any keyword.
 */
export function filterNavActions(query: string): PaletteNavAction[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...PALETTE_NAV_ACTIONS];
  return PALETTE_NAV_ACTIONS.filter(
    (action) =>
      action.label.toLowerCase().includes(q) ||
      action.keywords.some((k) => k.includes(q)),
  );
}

/** Queries shorter than this don't hit the API — single letters are noise. */
export const PALETTE_MIN_SEARCH_LENGTH = 2;

/** Debounce window between the last keystroke and the roster search. */
export const PALETTE_SEARCH_DEBOUNCE_MS = 150;
