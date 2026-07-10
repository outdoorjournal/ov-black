"use client";

// The Journal's day divider — one hairline crossing the full width of the
// view, so the day boundary reads as a rule the spine passes through rather
// than a bar that breaks it. The label sits in a gap on the line, offset past
// the spine gutter so it never overlaps the vertical threads. Still sticky
// while scrolling within its day ("Day 4 · Tue · 18 Mar"). Honors the
// Day-N-until-pinned rule (Wave E): weekday/date render only on an exact-dated
// trip; otherwise the honest ordinal stands alone.

import { formatDayTile } from "../../model/time";

import { SPINE_COL_PX } from "./Spine";

export function DayHeader({
  label,
  date,
  datesPinned,
}: {
  label: string;
  date: string;
  datesPinned: boolean;
}) {
  const { weekday, dayMonth } = formatDayTile(date);
  return (
    <header
      data-testid="journal-day-header"
      data-date={date}
      className="sticky top-0 z-20 flex items-center gap-3 py-2"
      style={{ "--spine-col": `${SPINE_COL_PX}px` } as React.CSSProperties}
    >
      {/* The left run crosses the spine gutter (and the vertical threads in
          it) before the label starts — the offset the gutter width defines. */}
      <span
        aria-hidden
        className="h-px w-[calc(var(--spine-col)+16px)] shrink-0 bg-ink/15"
      />
      <span className="flex shrink-0 items-baseline gap-3 rounded-full bg-paper/85 px-1 backdrop-blur-sm">
        <h2 className="font-serif text-[17px] leading-tight text-ink">
          {label}
        </h2>
        {datesPinned ? (
          <span className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
            {weekday} · {dayMonth}
          </span>
        ) : null}
      </span>
      <span aria-hidden className="h-px flex-1 bg-ink/15" />
    </header>
  );
}
