// Time helpers for the horizontal prototype.
//
// The vertical prototype maps one absolute timestamp → one y, with the y range
// covering the entire trip. Here we share a single 0..1440 (minute-of-day) y
// axis across every day column — that's what makes "9 a.m. in day 4" sit at
// the same y as "9 a.m. in day 8". So we re-export a few base utilities from
// the vertical lib and add minute-of-day specific helpers here.

export {
  parseIso,
  minutesBetween,
  minutesSince,
  addMinutesIso,
  formatClock,
  formatDuration,
  tzDayKey,
  startOfDayIso,
  hourOfDay,
  formatDayTile,
} from "./time";

import { parseIso } from "./time";

export const MINUTES_PER_DAY = 24 * 60;

// Minute-of-day in the traveler's local timezone, in [0, 1440).
export function localMinuteOfDay(iso: string, tzOffsetHours: number): number {
  const ms = parseIso(iso) + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

// Format an integer minute-of-day (0..1440) as "HH:MM".
export function formatMinuteOfDay(min: number): string {
  const m = ((min % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  const hh = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(Math.round(m % 60)).padStart(2, "0");
  return `${hh}:${mm}`;
}
