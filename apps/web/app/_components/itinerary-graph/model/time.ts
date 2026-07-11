export function parseIso(iso: string): number {
  return new Date(iso).getTime();
}

// The UTC offset (in hours, may be fractional) encoded in an ISO string, or
// null if it carries none. A trip spans timezones — each node's scheduled time
// is stored as an offset-bearing local ISO (e.g. "…16:10:00+09:00"), so the
// layout reads each node's OWN offset rather than one trip-wide value.
export function offsetHoursOf(iso: string): number | null {
  if (/Z$/.test(iso)) return 0;
  const m = /([+-])(\d{2}):?(\d{2})$/.exec(iso);
  if (!m) return null;
  const sign = m[1] === "-" ? -1 : 1;
  return sign * (Number(m[2]) + Number(m[3]) / 60);
}

// Resolve a node's own offset, falling back to a trip-level default when the
// string carries none (e.g. a UTC-only `starts_at` with no known tz).
export function offsetHoursOr(iso: string, fallbackHours: number): number {
  return offsetHoursOf(iso) ?? fallbackHours;
}

export function minutesBetween(fromIso: string, toIso: string): number {
  return (parseIso(toIso) - parseIso(fromIso)) / 60000;
}

export function minutesSince(windowStartIso: string, iso: string): number {
  return minutesBetween(windowStartIso, iso);
}

export function addMinutesIso(iso: string, minutes: number): string {
  return new Date(parseIso(iso) + minutes * 60000).toISOString();
}

export function formatClock(iso: string, tzOffsetHours: number): string {
  const ms = parseIso(iso) + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  // Day-scale durations (multi-day safaris, expeditions) read as days, not
  // a wall of hours — "4d" / "2d 6h", with sub-hour remainders dropped.
  if (minutes >= 24 * 60) {
    const d = Math.floor(minutes / (24 * 60));
    const h = Math.round((minutes - d * 24 * 60) / 60);
    if (h === 24) return `${d + 1}d`;
    return h === 0 ? `${d}d` : `${d}d ${h}h`;
  }
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes - h * 60);
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

export function tzDayKey(iso: string, tzOffsetHours: number): string {
  const ms = parseIso(iso) + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function startOfDayIso(dateKey: string, tzOffsetHours: number): string {
  const [y, m, d] = dateKey.split("-").map((s) => Number(s));
  const utcMs = Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1, 0, 0, 0);
  return new Date(utcMs - tzOffsetHours * 3600 * 1000).toISOString();
}

export function hourOfDay(iso: string, tzOffsetHours: number): number {
  const ms = parseIso(iso) + tzOffsetHours * 3600 * 1000;
  const d = new Date(ms);
  return d.getUTCHours() + d.getUTCMinutes() / 60;
}

// ── Wave E (ADV-16): strictly Day-N until pinned ─────────────────────────────
// On an unpinned trip (timing_kind ≠ "exact") a card's absolute date is a
// provisional coordinate, not a fact — rendering "Wed, Sep 24" would be a
// wrong-but-plausible date. Every date-bearing surface routes through these
// helpers: pinned trips show real dates, unpinned trips show honest "Day N"
// ordinals anchored at `days_anchor` (Day N ≡ days_anchor + (N−1)).

export type TripTimingLike = {
  timing_kind?: string | null;
  date_start?: string | null;
  // Day-1 anchor (0041). Read defensively until the generated client carries it.
  days_anchor?: string | null;
};

export function datesPinned(t: TripTimingLike | null | undefined): boolean {
  return t?.timing_kind === "exact";
}

/** The date "Day 1" currently maps to, or null when nothing anchors it yet. */
export function dayAnchorKey(t: TripTimingLike | null | undefined): string | null {
  if (!t) return null;
  if (t.timing_kind === "exact" && typeof t.date_start === "string" && t.date_start)
    return t.date_start;
  return typeof t.days_anchor === "string" && t.days_anchor ? t.days_anchor : null;
}

function diffDayKeys(fromKey: string, toKey: string): number {
  const [fy, fm, fd] = fromKey.split("-").map((s) => Number(s));
  const [ty, tm, td] = toKey.split("-").map(Number);
  const a = Date.UTC(fy ?? 1970, (fm ?? 1) - 1, fd ?? 1);
  const b = Date.UTC(ty ?? 1970, (tm ?? 1) - 1, td ?? 1);
  return Math.round((b - a) / 86_400_000);
}

/** 1-based Day ordinal for a YYYY-MM-DD key, or null when it can't be honest. */
export function dayOrdinal(
  t: TripTimingLike | null | undefined,
  dateKey: string,
): number | null {
  const anchor = dayAnchorKey(t);
  if (!anchor) return null;
  const n = diffDayKeys(anchor, dateKey) + 1;
  return n >= 1 ? n : null;
}

/**
 * The one when-stamp rule (Wave E): a node's scheduled ISO renders as a real
 * date ("Wed, Sep 24") only on a pinned trip; unpinned it renders the honest
 * ordinal ("Day 3"), and null when no anchor makes even that honest.
 */
export function formatNodeWhen(
  t: TripTimingLike | null | undefined,
  iso: string,
): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  if (datesPinned(t)) {
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }
  const key = tzDayKey(iso, offsetHoursOf(iso) ?? 0);
  const n = dayOrdinal(t, key);
  return n === null ? null : `Day ${n}`;
}

export function formatDayTile(dateKey: string): { weekday: string; dayMonth: string } {
  const [y, m, d] = dateKey.split("-").map((s) => Number(s));
  const date = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()] ?? "";
  const mo = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ][date.getUTCMonth()] ?? "";
  return { weekday: wd, dayMonth: `${date.getUTCDate()} ${mo}` };
}
