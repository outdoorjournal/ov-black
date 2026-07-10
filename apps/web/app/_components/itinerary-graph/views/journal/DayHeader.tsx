"use client";

// The Journal's day divider — sticky while scrolling within its day, so the
// reader always knows where in the trip they are ("Day 4 · Tue · 18 Mar").
// Honors the Day-N-until-pinned rule (Wave E): weekday/date render only on an
// exact-dated trip; otherwise the honest ordinal stands alone.

import { formatDayTile } from "../../model/time";

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
      className="sticky top-0 z-20 -mx-1 flex items-baseline gap-3 border-b border-ink/10 bg-paper/90 px-1 py-2 backdrop-blur-sm"
    >
      <h2 className="font-serif text-[17px] leading-tight text-ink">{label}</h2>
      {datesPinned ? (
        <span className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
          {weekday} · {dayMonth}
        </span>
      ) : null}
    </header>
  );
}
