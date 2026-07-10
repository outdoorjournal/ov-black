"use client";

// The parent-context header for a subgraph child (a journey beat): when the
// reader is looking at "day 3 of 4" of a packaged experience, the package's
// own card sits above it — the anchor of the journey — with a quiet "part of"
// eyebrow. Rendered by the Journal's right rail and the full card-detail
// destination; the caller decides what opening the parent does (focus the
// rail vs. navigate).

import type { NodeResponse } from "../model/types";
import { subgraphDayMeta } from "./subgraph";
import { NodeCard } from "../views/horizontal/NodeCard";

export function PartOfJourney({
  parent,
  child,
  siblingCount,
  tzOffsetHours,
  onOpenParent,
}: {
  /** The packaged experience node that owns the journey. */
  parent: NodeResponse;
  /** The beat being looked at — its day index feeds the eyebrow. */
  child: NodeResponse;
  /** How many days the journey has (the child's siblings, incl. itself). */
  siblingCount: number;
  tzOffsetHours: number;
  /** Open the parent (focus it in the rail / navigate to its detail). */
  onOpenParent: () => void;
}) {
  const index = subgraphDayMeta(child).index;
  return (
    <div data-testid="journey-parent-context" className="flex flex-col gap-1.5">
      <p className="font-sans text-[9px] uppercase tracking-[0.2em] text-ink/40">
        <span aria-hidden>↰ </span>
        part of
        {typeof index === "number" && siblingCount > 0
          ? ` · day ${index} of ${siblingCount}`
          : ""}
      </p>
      <NodeCard
        node={parent}
        tzOffsetHours={tzOffsetHours}
        onClick={onOpenParent}
      />
    </div>
  );
}
