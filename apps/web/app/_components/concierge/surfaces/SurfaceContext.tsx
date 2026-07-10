"use client";

// Opener handle for the drawer beside the chat.
//
// PlaceChip renders deep inside ProseMessage, which is shared by surfaces
// that have no drawer (the advisor concierge panel, the human thread). The
// context is therefore nullable-by-default: inside ChatShell's provider a
// chip opens the drawer; everywhere else `useSurfaceOpener()` returns null
// and the chip falls back to its original inline popover.

import { createContext, useContext } from "react";

import type { ActiveSurface } from "./types";

export type SurfaceOpener = {
  open: (surface: ActiveSurface) => void;
};

export const SurfaceContext = createContext<SurfaceOpener | null>(null);

export function useSurfaceOpener(): SurfaceOpener | null {
  return useContext(SurfaceContext);
}
