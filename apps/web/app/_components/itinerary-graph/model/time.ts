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
