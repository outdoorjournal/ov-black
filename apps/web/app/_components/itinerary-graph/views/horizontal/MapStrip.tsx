"use client";

// Bottom map strip. The horizontal layout fills its height with day columns,
// so unlike the vertical prototype (which fades a full-height map into the
// right ~60vw), the map lives below the timeline as a tall strip. We apply a
// vertical alpha mask to the map so its top edge softly emerges from the
// paper backdrop instead of sitting under a hard rule — same fade idiom the
// vertical prototype uses on its right-side ambient backdrop, just rotated
// 90°.

import { MapFlyer, type MapArc, type MapFocus } from "../../shared/MapFlyer";

interface MapStripProps {
  focus: MapFocus | null;
  arc?: MapArc | null;
  height?: number;
}

// Match the vertical prototype's AmbientBackdrop fade, rotated to vertical:
// transparent at the very top, fully opaque past ~38% down. The transition
// zone reveals the paper background, so the map looks like it emerges from
// the page rather than docking against a hard edge.
const FADE_MASK =
  "linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.4) 12%, rgba(0,0,0,0.85) 25%, rgba(0,0,0,1) 38%)";
const FADE_STYLE = {
  WebkitMaskImage: FADE_MASK,
  maskImage: FADE_MASK,
} as const;

export function MapStrip({ focus, arc = null, height = 220 }: MapStripProps) {
  return (
    <div className="relative w-full" style={{ height }}>
      <div className="absolute inset-0" style={FADE_STYLE}>
        <MapFlyer focus={focus} arc={arc} />
      </div>
      {/* Label rides above the fade so it stays legible at the very top
          where the map itself is mostly transparent. */}
      <div className="pointer-events-none absolute left-3 top-2 z-10 flex items-baseline gap-2 rounded-md bg-paper/85 px-2.5 py-1 backdrop-blur-xs">
        <span className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
          On the map
        </span>
        {focus?.label ? (
          <span className="font-serif text-[13px] text-ink">{focus.label}</span>
        ) : null}
      </div>
    </div>
  );
}
