"use client";

// The day chooser that sits above the mobile timeline: a horizontally
// scrollable row of day pills. Tapping a pill (or swiping the timeline below)
// selects a day; the active pill auto-centers so the current day is always in
// view even on a long trip.

import { useEffect, useRef } from "react";

import { formatDayTile } from "../../model/horizontalTime";
import type { DayGroup } from "../../shared/groupNodesByDay";

interface DayStripProps {
  groups: DayGroup[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export function DayStrip({ groups, activeIndex, onSelect }: DayStripProps) {
  const ref = useRef<HTMLDivElement>(null);

  // Keep the active pill centered as the selection moves (from taps or swipes).
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>(
      `[data-day-index="${activeIndex}"]`,
    );
    el?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [activeIndex]);

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label="Itinerary days"
      className="flex shrink-0 gap-2 overflow-x-auto border-b border-ink/10 px-3 py-2 scrollbar-none [&::-webkit-scrollbar]:hidden"
    >
      {groups.map((g, i) => {
        const { weekday, dayMonth } = formatDayTile(g.date);
        const active = i === activeIndex;
        return (
          <button
            key={g.date}
            type="button"
            role="tab"
            aria-selected={active}
            data-day-index={i}
            onClick={() => onSelect(i)}
            className={[
              "flex shrink-0 flex-col items-start rounded-xl border px-3 py-1.5 text-left transition-colors",
              active
                ? "border-ink/30 bg-ink/10"
                : "border-ink/10 bg-paper/70 hover:bg-ink/5",
            ].join(" ")}
          >
            <span className="text-[9px] uppercase tracking-[0.18em] text-ink/50">
              {weekday}
            </span>
            <span className="font-serif text-[14px] leading-tight text-ink">
              {g.label}
            </span>
            <span className="mt-0.5 text-[9px] text-ink/45">
              {dayMonth}
              {g.weather_emoji ? ` · ${g.weather_emoji}` : ""}
              {g.items.length > 0 ? ` · ${g.items.length}` : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}
