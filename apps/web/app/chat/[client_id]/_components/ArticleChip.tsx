"use client";

// Inline reading chip. The concierge references a saved read mid-sentence as a
// markdown link with an `article:` scheme — `[Mt. Olympus…](article:<nodeId>)` —
// and ProseMessage swaps the anchor for this component. It renders as an
// editorial reference (a book glyph, the title with a quiet brand underline)
// that inherits the prose type — NOT the PlaceChip pill: article titles are a
// dozen words, and a rounded-full pill wrapped over two centered lines reads
// as a gray slab, not punctuation.
//
// Tapping it opens the article flyout beside the chat — the same drawer the
// basecamp `suggest_reading` surface uses, but for a piece that's ALREADY in the
// reading list (the campaign kickoff pre-saved it), so the flyout opens showing
// "Added". Resolution is client-side: the read is a node in the itinerary graph
// store, and ArticleResolverContext turns the node id into the flyout's view.
//
// Constraints (shared with PlaceChip): it lives inside a markdown <p>, so the
// whole subtree is inline elements (span/button), never a <div>. Outside the
// itinerary shell — where there's no reading store or drawer — both the opener
// and the resolver are null and the chip degrades to a plain inline label.

import { BookOpen } from "lucide-react";

import {
  useArticleResolver,
  useSurfaceOpener,
} from "@/app/_components/concierge/surfaces/SurfaceContext";
import { cn } from "@/lib/utils";

export type ArticleChipProps = {
  // The read's graph-node id (everything after `article:` in the link target).
  nodeId: string;
  // The visible label (the markdown link text) — the article title.
  label: string;
};

export function ArticleChip({ nodeId, label }: ArticleChipProps) {
  const opener = useSurfaceOpener();
  const resolve = useArticleResolver();
  const article = resolve ? resolve(nodeId) : null;

  // No drawer or no resolvable read (basecamp prose, a stale id) → a quiet
  // inline label. The chip still marks the piece; it just can't open a flyout.
  if (!opener || !article) {
    return <span className="font-medium text-ink">{label}</span>;
  }

  return (
    <button
      type="button"
      data-testid="article-chip"
      data-article-node={nodeId}
      onClick={() =>
        opener.open({
          kind: "article",
          surfaceId: `article-${nodeId}`,
          article,
          alreadySaved: true,
        })
      }
      className={cn(
        "inline max-w-full text-left align-baseline font-medium text-ink transition-colors",
        "underline decoration-brand/40 decoration-1 underline-offset-[3px]",
        "hover:text-brand hover:decoration-brand",
      )}
    >
      <BookOpen
        className="mr-1 inline-block h-[0.85em] w-[0.85em] -translate-y-px text-brand"
        aria-hidden
      />
      {label}
    </button>
  );
}
