// dayRail — pure derivations behind the Journal's floating day minimap and
// the more-below tail cue (traveler-journal design, phase 5). View-free and
// unit-testable: everything here reads the `toJournal` output, so the day
// rail, the elision markers, and the day headers share ONE indexing scheme
// (the adapter's 0-based day scaffold) and can never drift apart.

import type { Journal } from "./toJournal";

export type DayRailDay = {
  kind: "day";
  date: string;
  /** The scaffold's ordinal label ("Day 4"). */
  label: string;
  /** 0-based index into the trip's day scaffold. */
  index: number;
};

/** A collapsed multi-day span — ONE compressed tick on the rail (per-day dots
 *  for a 30-day elision would defeat the compression the elision buys). */
export type DayRailElision = {
  kind: "elision";
  startDate: string;
  endDate: string;
  dayCount: number;
  startIndex: number;
  endIndex: number;
};

export type DayRailItem = DayRailDay | DayRailElision;

/** The rail's items, in journey order — one dot per rendered day section,
 *  one compressed tick per elision. */
export function dayRailItems(journal: Journal): DayRailItem[] {
  return journal.sections.map((section): DayRailItem => {
    if (section.kind === "day") {
      return {
        kind: "day",
        date: section.date,
        label: section.label,
        index: section.index,
      };
    }
    const first = section.days[0];
    const last = section.days[section.days.length - 1];
    return {
      kind: "elision",
      startDate: section.startDate,
      endDate: section.endDate,
      dayCount: section.dayCount,
      startIndex: first?.index ?? 0,
      endIndex: last?.index ?? 0,
    };
  });
}

/** Every scaffold index the rail covers, in order — day dots contribute their
 *  own index, elision ticks their whole run. The agreement invariant (tested):
 *  this is exactly 0..totalDays-1 with no gaps and no duplicates, i.e. the
 *  rail and the elisions never disagree about day indexing. */
export function railIndexCoverage(items: DayRailItem[]): number[] {
  const out: number[] = [];
  for (const item of items) {
    if (item.kind === "day") {
      out.push(item.index);
    } else {
      for (let i = item.startIndex; i <= item.endIndex; i += 1) out.push(i);
    }
  }
  return out;
}

/** node id → the 0-based scaffold day index its row renders under (cards,
 *  alternative-group members, and diff-mode ghosts alike) — how the rail
 *  resolves "which day is the reader on" from the active node. */
export function dayIndexByNode(journal: Journal): Map<string, number> {
  const map = new Map<string, number>();
  for (const section of journal.sections) {
    if (section.kind !== "day") continue;
    for (const entry of section.entries) {
      if (entry.kind === "node" || entry.kind === "ghost") {
        map.set(entry.node.id, section.index);
      } else if (entry.kind === "alt") {
        for (const n of entry.nodes) map.set(n.id, section.index);
      }
    }
  }
  return map;
}

// ── The more-below tail cue ───────────────────────────────────────────────────
/** One rendered section's measurement: its viewport-relative top and how many
 *  scaffold days it stands for (1 for a day, `dayCount` for an elision). */
export type TailProbe = { top: number; days: number; date: string | null };

/** How much journey is still below the fold: total off-screen days + the date
 *  of the first off-screen section (the jump pill's target). */
export function tailBelow(
  probes: TailProbe[],
  viewportBottom: number,
): { days: number; date: string | null } {
  let days = 0;
  let date: string | null = null;
  for (const probe of probes) {
    if (probe.top <= viewportBottom) continue;
    days += probe.days > 0 ? probe.days : 1;
    if (date === null) date = probe.date;
  }
  return { days, date };
}
