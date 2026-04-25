"use client";

import { sunStopsForDay } from "../_lib/sun";
import { formatDayTile, formatDuration } from "../_lib/time";
import type { TimelineSegment } from "../_state/layout";

interface TimeAxisProps {
  days: Array<{
    date: string;
    y: number;
    height: number;
    weather_emoji?: string;
    label: string;
  }>;
  segments: TimelineSegment[];
  pxPerMinute: number;
  totalHeight: number;
}

export function TimeAxis({
  days,
  segments,
  pxPerMinute,
  totalHeight,
}: TimeAxisProps) {
  const minor = pxPerMinute > 3.0 ? 15 : pxPerMinute > 1.5 ? 30 : 60;
  const major = pxPerMinute > 3.0 ? 60 : pxPerMinute > 1.5 ? 180 : 360;

  return (
    <div
      className="relative w-[110px] shrink-0 border-r border-ink/10 bg-paper/80 backdrop-blur-sm"
      style={{ minHeight: totalHeight }}
    >
      {/* Sun gradient + hash marks per live segment */}
      {segments.map((seg, i) =>
        seg.type === "live" ? (
          <LiveSegmentLayer
            key={`live-${i}`}
            seg={seg}
            minorMin={minor}
            majorMin={major}
            pxPerMinute={pxPerMinute}
          />
        ) : (
          <ElideBand key={`elide-${i}`} seg={seg} />
        ),
      )}

      {/* Day tiles render at their mapped y positions */}
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

function LiveSegmentLayer({
  seg,
  minorMin,
  majorMin,
  pxPerMinute,
}: {
  seg: TimelineSegment;
  minorMin: number;
  majorMin: number;
  pxPerMinute: number;
}) {
  const heightPx = seg.yEnd - seg.yStart;
  const sunCss = sunGradientForSegment(seg);

  // First minor tick at or after seg.startMin
  const firstMinor = Math.ceil(seg.startMin / minorMin) * minorMin;
  const ticks: Array<{ minute: number; major: boolean }> = [];
  for (let m = firstMinor; m <= seg.endMin; m += minorMin) {
    ticks.push({ minute: m, major: m % majorMin === 0 });
  }

  return (
    <>
      <div
        aria-hidden
        className="absolute left-0 w-full"
        style={{
          top: seg.yStart,
          height: heightPx,
          backgroundImage: sunCss,
          opacity: 0.22,
          mixBlendMode: "multiply",
        }}
      />
      {ticks.map((t) => {
        const offsetMin = t.minute - seg.startMin;
        const top = seg.yStart + offsetMin * pxPerMinute;
        const hh = Math.floor((t.minute % (24 * 60)) / 60);
        const mm = (t.minute % 60 + 60) % 60;
        const timeLabel = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
        return (
          <div
            key={`${seg.yStart}-${t.minute}`}
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
            {t.major ? (
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
    </>
  );
}

function ElideBand({ seg }: { seg: TimelineSegment }) {
  const heightPx = seg.yEnd - seg.yStart;
  const elidedMinutes = seg.endMin - seg.startMin;
  return (
    <div
      className="absolute left-0 w-full"
      style={{ top: seg.yStart, height: heightPx }}
      aria-label={`${formatDuration(elidedMinutes)} elided`}
    >
      <div
        aria-hidden
        className="absolute inset-0 opacity-50"
        style={{
          backgroundImage:
            "repeating-linear-gradient(90deg, transparent 0 4px, rgba(10,10,10,0.18) 4px 5px)",
        }}
      />
      <div className="absolute inset-x-1 top-1/2 -translate-y-1/2 text-center text-[8px] uppercase tracking-[0.18em] text-ink/55">
        {formatDuration(elidedMinutes)}
      </div>
    </div>
  );
}

function sunGradientForSegment(seg: TimelineSegment): string {
  // Map seg.startMin/seg.endMin → hour-of-day stops (mod 24h).
  const stops = sunStopsForDay();
  const startHour = (seg.startMin / 60) % 24;
  const endHour = (seg.endMin / 60) % 24;
  // If the segment spans <= 24h within a single day-slice, sample the hours.
  const span = (seg.endMin - seg.startMin) / 60;
  if (span >= 24) {
    return `linear-gradient(180deg, ${stops
      .map((s) => `${s.color} ${s.pct.toFixed(2)}%`)
      .join(", ")})`;
  }
  // Build gradient by sampling sun colors across [startHour, startHour+span].
  const samples: Array<{ pct: number; color: string }> = [];
  const N = 6;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    let h = (startHour + t * span) % 24;
    if (h < 0) h += 24;
    const color = sampleSunColor(h);
    // Cross-day wrap fallback: if endHour < startHour, the loop above uses % 24
    // which still produces sensible colors even across midnight.
    void endHour;
    samples.push({ pct: t * 100, color });
  }
  return `linear-gradient(180deg, ${samples
    .map((s) => `${s.color} ${s.pct.toFixed(2)}%`)
    .join(", ")})`;
}

function sampleSunColor(hour: number): string {
  const stops = sunStopsForDay();
  const pct = (hour / 24) * 100;
  let lo = stops[0]!;
  let hi = stops[stops.length - 1]!;
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i]!;
    const b = stops[i + 1]!;
    if (pct >= a.pct && pct <= b.pct) {
      lo = a;
      hi = b;
      break;
    }
  }
  const t = (pct - lo.pct) / Math.max(1e-6, hi.pct - lo.pct);
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
