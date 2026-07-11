interface Stop {
  hour: number;
  color: string;
}

const STOPS: Stop[] = [
  { hour: 0, color: "#14173d" },
  { hour: 4.5, color: "#4a3a6a" },
  { hour: 6, color: "#eb8a5a" },
  { hour: 9, color: "#f1c06b" },
  { hour: 12, color: "#f9ebb6" },
  { hour: 17, color: "#e88a4a" },
  { hour: 19, color: "#8a4d7a" },
  { hour: 20.5, color: "#4a3862" },
  { hour: 24, color: "#14173d" },
];

export function sunStopsForDay(): Array<{ pct: number; color: string }> {
  return STOPS.map((s) => ({ pct: (s.hour / 24) * 100, color: s.color }));
}

export function sunGradientCss(): string {
  const stops = sunStopsForDay()
    .map((s) => `${s.color} ${s.pct.toFixed(2)}%`)
    .join(", ");
  return `linear-gradient(180deg, ${stops})`;
}

/** The sky color at a given clock hour (0–24, wraps), interpolated between the
 *  daylight STOPS. Lets non-axis surfaces (e.g. the Journal's dusk wash) sample
 *  the same palette as the horizontal timeline's sun gradient. */
export function sunColorAtHour(hour: number): string {
  let h = hour % 24;
  if (h < 0) h += 24;
  let lo = STOPS[0]!;
  let hi = STOPS[STOPS.length - 1]!;
  for (let i = 0; i < STOPS.length - 1; i++) {
    const a = STOPS[i]!;
    const b = STOPS[i + 1]!;
    if (h >= a.hour && h <= b.hour) {
      lo = a;
      hi = b;
      break;
    }
  }
  const t = (h - lo.hour) / Math.max(1e-6, hi.hour - lo.hour);
  return mixHex(lo.color, hi.color, t);
}

function mixHex(a: string, b: string, t: number): string {
  const ah = parseHex(a);
  const bh = parseHex(b);
  const r = Math.round(ah[0] + (bh[0] - ah[0]) * t);
  const g = Math.round(ah[1] + (bh[1] - ah[1]) * t);
  const bl = Math.round(ah[2] + (bh[2] - ah[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function parseHex(hex: string): [number, number, number] {
  const v = hex.replace("#", "");
  return [
    parseInt(v.slice(0, 2), 16),
    parseInt(v.slice(2, 4), 16),
    parseInt(v.slice(4, 6), 16),
  ];
}
