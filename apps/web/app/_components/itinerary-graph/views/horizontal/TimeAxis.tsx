"use client";

// Shared minute-of-day y axis. Renders the sun-color gradient (single 24h
// sweep, since every column shares 0..1440), elision bands, and hour labels.

import { sunStopsForDay } from "../../model/sun";
import { formatDuration } from "../../model/horizontalTime";
import type { TimelineSegment, TimeMarker } from "./layout";

interface TimeAxisProps {
  segments: TimelineSegment[];
  pxPerMinute: number;
  totalHeight: number;
  timeMarkers: TimeMarker[];
}

// When two hour labels would render within this distance the lower one is
// nudged down so they don't overlap. Same idea as the vertical prototype.
const MARKER_MIN_GAP_PX = 14;

export function TimeAxis({
  segments,
  pxPerMinute,
  totalHeight,
  timeMarkers,
}: TimeAxisProps) {
  const minor = pxPerMinute > 3.0 ? 15 : pxPerMinute > 1.5 ? 30 : 60;
  const dedupedMarkers = dedupeMarkersByGap(timeMarkers, MARKER_MIN_GAP_PX);
  return (
    <div
      className="relative w-[96px] shrink-0 border-r border-ink/10 bg-paper/85 backdrop-blur-sm"
      style={{ minHeight: totalHeight }}
    >
      {/* Sun gradient + tick marks per live segment. */}
      {segments.map((seg, i) =>
        seg.type === "live" ? (
          <LiveSegmentLayer key={`live-${i}`} seg={seg} minorMin={minor} />
        ) : (
          <ElideBand key={`elide-${i}`} seg={seg} />
        ),
      )}

      {/* Hour labels — one per HH:00 that falls inside a live segment. */}
      {dedupedMarkers.map((m) => (
        <div
          key={`marker-${m.label}-${m.y}`}
          className="pointer-events-none absolute right-0 flex items-center gap-1.5"
          style={{ top: m.y - 6 }}
        >
          <span className="font-mono text-[10px] tracking-[0.1em] text-ink/65">
            {m.label}
          </span>
          <span aria-hidden className="h-px w-2.5 bg-ink/40 opacity-70" />
        </div>
      ))}

    </div>
  );
}

function LiveSegmentLayer({
  seg,
  minorMin,
}: {
  seg: TimelineSegment;
  minorMin: number;
}) {
  const heightPx = seg.yEnd - seg.yStart;
  const minutesSpan = seg.endMin - seg.startMin || 1;
  const sunCss = sunGradientForSegment(seg);

  const firstMinor = Math.ceil(seg.startMin / minorMin) * minorMin;
  const ticks: number[] = [];
  for (let m = firstMinor; m <= seg.endMin; m += minorMin) {
    ticks.push(m);
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
      {ticks.map((minute) => {
        // Interpolate within this segment's actual y span. Stretched
        // segments (split by applyStretchesToSegments at every stretch
        // atMin) have effective px-per-minute = heightPx / minutesSpan, not
        // the input pxPerMinute. Using the global pxPerMinute here would
        // place ticks at the wrong y inside any stretched segment, which is
        // what made cards look misaligned even when their y was correct.
        const t = (minute - seg.startMin) / minutesSpan;
        const top = seg.yStart + t * heightPx;
        return (
          <div
            key={`${seg.yStart}-${minute}`}
            aria-hidden
            className="absolute"
            style={{
              right: 0,
              top: top - 0.5,
              width: 5,
              height: 1,
              backgroundColor: "rgba(10,10,10,0.32)",
              opacity: 0.4,
            }}
          />
        );
      })}
    </>
  );
}

// Drop labels that would render within `minGap` of an already-kept label,
// rather than shifting them down. Cards on this axis are anchored to their
// own labels' y; if a co-minute label gets nudged for visual breathing room,
// the card no longer aligns with it. We bias toward keeping HH:00 hour
// labels (more useful as a clock) when they collide with an off-the-hour
// card-time label.
function dedupeMarkersByGap(markers: TimeMarker[], minGap: number): TimeMarker[] {
  if (markers.length === 0) return markers;
  const out: TimeMarker[] = [];
  let lastY = Number.NEGATIVE_INFINITY;
  for (const m of markers) {
    if (m.y - lastY < minGap) {
      // Replace the previous label with this one if this one is on-the-hour
      // and the previous wasn't.
      const prev = out[out.length - 1];
      const isHour = m.label.endsWith(":00");
      const prevIsHour = prev?.label.endsWith(":00");
      if (isHour && prev && !prevIsHour) {
        out[out.length - 1] = m;
        lastY = m.y;
      }
      continue;
    }
    out.push(m);
    lastY = m.y;
  }
  return out;
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
  const startHour = (seg.startMin / 60) % 24;
  const span = (seg.endMin - seg.startMin) / 60;
  if (span >= 24) {
    return `linear-gradient(180deg, ${sunStopsForDay()
      .map((s) => `${s.color} ${s.pct.toFixed(2)}%`)
      .join(", ")})`;
  }
  const samples: Array<{ pct: number; color: string }> = [];
  const N = 6;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    let h = (startHour + t * span) % 24;
    if (h < 0) h += 24;
    samples.push({ pct: t * 100, color: sampleSunColor(h) });
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
