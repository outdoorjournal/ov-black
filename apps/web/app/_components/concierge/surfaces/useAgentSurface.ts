"use client";

// The shared half of hosting the drawer — every chat surface (basecamp
// first-touch card, basecamp rail, itinerary concierge, the full chat page)
// uses this one hook instead of hand-rolling surface state. A host wires:
//
//   const { surface, onSurface, opener, close } = useAgentSurface();
//   useAgentStream({ ..., onSurface });                    // agent-pushed panels
//   <SurfaceContext.Provider value={opener}>…prose…</…>    // chip-opened panels
//   <AgentSurface surface={surface} onClose={close} … />   // in a relative box
//
// Keeping the state here (per host, plain useState) rather than in each
// screen's zustand store means a new panel kind lands everywhere by touching
// only the surfaces/ module — the four chat shells stay layout-only.

import { useCallback, useMemo, useState } from "react";

import type { SurfaceFrame } from "@/lib/agentStream";

import type { SurfaceOpener } from "./SurfaceContext";
import { surfaceFromFrame, type ActiveSurface, type OptionView } from "./types";

export type AgentSurfaceHost = {
  surface: ActiveSurface | null;
  /** Plug into useAgentStream's onSurface — tolerant-parses and opens. */
  onSurface: (frame: SurfaceFrame) => void;
  /** Provide via SurfaceContext so PlaceChips open the drawer. */
  opener: SurfaceOpener;
  close: () => void;
};

export function useAgentSurface(): AgentSurfaceHost {
  const [surface, setSurface] = useState<ActiveSurface | null>(null);

  const onSurface = useCallback((frame: SurfaceFrame) => {
    // Tolerant narrowing: an unknown kind or malformed payload drops the
    // panel rather than opening a broken drawer (or crashing the stream).
    const next = surfaceFromFrame(frame);
    if (next) setSurface(next);
  }, []);

  const opener = useMemo<SurfaceOpener>(() => ({ open: setSurface }), []);
  const close = useCallback(() => setSurface(null), []);

  return { surface, onSurface, opener, close };
}

/**
 * The traveler's reply when they tap an option — composed once here so every
 * host answers in the same voice (and transcripts stay consistent).
 */
export function optionReply(option: OptionView): string {
  return `I'd like to go with "${option.title}".`;
}
