"use client";

import { sunGradientCss } from "../_lib/sun";
import { formatDayTile } from "../_lib/time";

interface TimeAxisProps {
  days: Array<{ date: string; y: number; height: number; weather_emoji?: string; label: string }>;
  pxPerMinute: number;
  totalHeight: number;
}

export function TimeAxis({ days, pxPerMinute, totalHeight }: TimeAxisProps) {
  // Decide tick density by zoom.
  const minor = pxPerMinute > 3.0 ? 15 : pxPerMinute > 1.5 ? 30 : 60;
  const major = pxPerMinute > 3.0 ? 60 : pxPerMinute > 1.5 ? 180 : 360;

  return (
    <div
      className="relative w-[110px] shrink-0 border-r border-ink/10 bg-paper"
      style={{ minHeight: totalHeight }}
    >
      {days.map((d) => (
        <DaySunLayer key={d.date} y={d.y} height={d.height} />
      ))}
      {days.map((d) => (
        <DayTicks
          key={`ticks-${d.date}`}
          y={d.y}
          height={d.height}
          minorMin={minor}
          majorMin={major}
          pxPerMinute={pxPerMinute}
        />
      ))}
      {days.map((d) => (
        <DayTile
          key={`tile-${d.date}`}
          y={d.y}
          date={d.date}
          label={d.label}
          {...(d.weather_emoji ? { weather_emoji: d.weather_emoji } : {})}
        />
      ))}
    </div>
  );
}

function DaySunLayer({ y, height }: { y: number; height: number }) {
  return (
    <div
      aria-hidden
      className="absolute left-0 w-full"
      style={{
        top: y,
        height,
        backgroundImage: sunGradientCss(),
        opacity: 0.22,
        mixBlendMode: "multiply",
      }}
    />
  );
}

function DayTicks({
  y,
  height,
  minorMin,
  majorMin,
  pxPerMinute,
}: {
  y: number;
  height: number;
  minorMin: number;
  majorMin: number;
  pxPerMinute: number;
}) {
  const ticks: Array<{ minute: number; major: boolean }> = [];
  for (let m = 0; m <= 24 * 60; m += minorMin) {
    ticks.push({ minute: m, major: m % majorMin === 0 });
  }
  return (
    <div className="absolute left-0 top-0 w-full" style={{ top: y, height }}>
      {ticks.map((t) => {
        const top = t.minute * pxPerMinute;
        const hh = Math.floor(t.minute / 60);
        const mm = t.minute - hh * 60;
        const timeLabel = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
        return (
          <div
            key={t.minute}
            className="absolute left-0 right-0"
            style={{ top }}
          >
            <div
              className="absolute"
              style={{
                right: 0,
                top: -0.5,
                width: t.major ? 16 : 6,
                height: 1,
                backgroundColor: "rgba(10,10,10,0.35)",
                opacity: t.major ? 0.6 : 0.35,
              }}
            />
            {t.major && t.minute < 24 * 60 ? (
              <span
                className="absolute text-[9px] tracking-[0.1em] text-ink/55"
                style={{ right: 20, top: -6 }}
              >
                {timeLabel}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function DayTile({
  y,
  date,
  label,
  weather_emoji,
}: {
  y: number;
  date: string;
  label: string;
  weather_emoji?: string;
}) {
  const { weekday, dayMonth } = formatDayTile(date);
  return (
    <div
      className="absolute left-1 right-1 z-10 rounded-sm border border-ink/15 bg-paper px-2 py-1 shadow-sm"
      style={{ top: y }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute -top-1 left-2 h-2 w-8 rotate-[-2deg] bg-amber-600/40"
        style={{ mixBlendMode: "multiply" }}
      />
      <div className="text-[9px] uppercase tracking-[0.2em] text-ink/50">{label}</div>
      <div className="font-serif text-[11px] leading-tight text-ink">{weekday} · {dayMonth}</div>
      {weather_emoji ? (
        <div className="text-[12px] leading-none">{weather_emoji}</div>
      ) : null}
    </div>
  );
}
