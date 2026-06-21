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
