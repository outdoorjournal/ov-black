"use client";

// Opener handle for the drawer beside the chat.
//
// PlaceChip renders deep inside ProseMessage, which is shared by surfaces
// that have no drawer (the advisor concierge panel, the human thread). The
// context is therefore nullable-by-default: inside ChatShell's provider a
// chip opens the drawer; everywhere else `useSurfaceOpener()` returns null
// and the chip falls back to its original inline popover.

import { createContext, useContext } from "react";

import type { ActiveSurface, ArticleSurfaceView } from "./types";

export type SurfaceOpener = {
  open: (surface: ActiveSurface) => void;
};

export const SurfaceContext = createContext<SurfaceOpener | null>(null);

export function useSurfaceOpener(): SurfaceOpener | null {
  return useContext(SurfaceContext);
}

// Resolves an `[label](article:<nodeId>)` chip to the read it stands for.
//
// ArticleChip renders deep inside ProseMessage, which is shared by surfaces
// with no reading store (basecamp, the human thread). Like SurfaceContext this
// is nullable-by-default: inside the itinerary shell the provider resolves the
// node from the graph store; everywhere else the resolver is null and the chip
// degrades to a plain inline label.
export type ArticleResolver = (nodeId: string) => ArticleSurfaceView | null;

export const ArticleResolverContext = createContext<ArticleResolver | null>(null);

export function useArticleResolver(): ArticleResolver | null {
  return useContext(ArticleResolverContext);
}
