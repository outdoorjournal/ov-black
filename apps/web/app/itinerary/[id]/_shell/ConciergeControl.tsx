"use client";

// A tiny imperative channel for the persistent concierge (M006/PS4). The shell
// owns the overlay open/close state (<1100px it's summonable), but a routed
// child — the card detail's "Ask Artemis about this" — needs to summon it.
//
// This can't live in the graph store: the shell HOSTS that store's Provider, so
// the shell can't consume its own store to flip an open flag. So the shell keeps
// the flag in React state and exposes `openConcierge` through this context; any
// descendant (inside the store Provider or not) can call it.

import { createContext, useContext } from "react";

type ConciergeControl = { openConcierge: () => void };

const ConciergeControlContext = createContext<ConciergeControl | null>(null);

export const ConciergeControlProvider = ConciergeControlContext.Provider;

/** Summon the persistent concierge. A no-op outside the shell (e.g. a facet
 *  rendered in isolation under test) so callers never have to null-check. */
export function useConciergeControl(): ConciergeControl {
  return useContext(ConciergeControlContext) ?? { openConcierge: () => {} };
}
