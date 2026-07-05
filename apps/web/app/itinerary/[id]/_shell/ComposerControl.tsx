"use client";

// Imperative channel for the advisor card composer (ADV-4). Like
// ConciergeControl, the shell owns the composer's open state (it hosts the
// graph-store Provider, so it can't consume its own store to flip a flag), and
// exposes `openComposer` through this context. Any descendant — the Studio
// "Add a card" button, the Collection add affordance, or an empty timeline slot
// — summons the same composer, optionally pre-set to a day + minute so the card
// lands scheduled at that slot (Outlook-style) instead of in the Collection.

import { createContext, useContext } from "react";

/** A day (YYYY-MM-DD) + minute-of-day to pre-schedule the card at, or null to
 *  compose an unscheduled Collection item. */
export type ComposerPrefill = { dayKey: string; minute: number } | null;

type ComposerControl = { openComposer: (prefill?: ComposerPrefill) => void };

const ComposerControlContext = createContext<ComposerControl | null>(null);

export const ComposerControlProvider = ComposerControlContext.Provider;

/** Summon the card composer. A no-op outside the shell (e.g. a facet rendered
 *  in isolation under test) so callers never have to null-check. */
export function useComposerControl(): ComposerControl {
  return useContext(ComposerControlContext) ?? { openComposer: () => {} };
}
