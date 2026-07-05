"use client";

// Glance card for a scheduled timeline node: a CardShell wearing the shared
// paper substrate + status footer, filled with the shared CardBody (the
// type-specific "signature detail"). The compact strip variant swaps CardBody
// for the shell's inline CompactBody. The body switcher + inferCardKind now live
// in shared/cards/CardBody so the Collection and chat cards render identically.

import { CardShell, CompactBody } from "../../shared/cards/CardShell";
import {
  CardBody,
  inferCardKind,
  statusToKind,
} from "../../shared/cards/CardBody";

import {
  formatClock,
  formatDuration,
  offsetHoursOr,
} from "../../model/horizontalTime";
import type { NodeResponse } from "../../model/horizontalTypes";
import { getHMeta } from "../../model/horizontalTypes";

interface NodeCardProps {
  node: NodeResponse;
  tzOffsetHours: number;
  onClick?: () => void;
  flash?: boolean;
  // When the parent layout is below the compact zoom breakpoint, render
  // the strip variant (180px-wide, single-line) instead of the glance card.
  compact?: boolean;
  // Count of `note` nodes attached to this one (0014). When > 0 the card shows
  // a small badge; the notes themselves are read in the expanded detail sheet.
  attachedNoteCount?: number;
}

export function NodeCard({
  node,
  tzOffsetHours,
  onClick,
  flash,
  compact = false,
  attachedNoteCount = 0,
}: NodeCardProps) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);

  // Make the whole shell a button so cards click-through to a detail sheet
  // and we keep the keyboard semantics the cards prototype already gives.
  const wrapperClass = [
    "relative block w-full text-left",
    flash ? "ring-2 ring-brand rounded-lg" : "",
    "transition-shadow",
  ].join(" ");

  const width = compact ? "compact" : "glance";
  const meta = getHMeta(node);
  const start = meta.start_time
    ? formatClock(meta.start_time, offsetHoursOr(meta.start_time, tzOffsetHours))
    : null;
  const dur =
    typeof meta.duration_minutes === "number"
      ? formatDuration(meta.duration_minutes)
      : null;

  return (
    <button type="button" onClick={onClick} className={wrapperClass}>
      <CardShell
        kind={kind}
        status={status}
        width={width}
        lockReason={node.lock_reason ?? null}
        lockLabel={node.type}
      >
        {compact ? (
          <CompactBody
            kind={kind}
            title={node.title}
            time={start}
            duration={dur}
          />
        ) : (
          <CardBody node={node} kind={kind} tzOffsetHours={tzOffsetHours} />
        )}
      </CardShell>
      {attachedNoteCount > 0 ? (
        <span
          data-testid="attached-note-badge"
          aria-label={`${attachedNoteCount} note${attachedNoteCount === 1 ? "" : "s"}`}
          className="pointer-events-none absolute -right-1.5 -top-1.5 z-10 flex h-5 min-w-5 items-center justify-center rounded-full border border-amber-900/25 bg-[#fbf1c7] px-1 font-sans text-[10px] font-semibold leading-none text-amber-900 shadow-xs"
        >
          ✎ {attachedNoteCount}
        </span>
      ) : null}
    </button>
  );
}
