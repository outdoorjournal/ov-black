"use client";

import { MapFlyer, type MapArc, type MapFocus } from "./MapFlyer";

interface AmbientBackdropProps {
  focus: MapFocus | null;
  arc?: MapArc | null;
}

// Alpha mask: transparent on the left, opaque on the right. Applied to the
// *visual* layers (map + image) only, so the parent keeps its dimensions and
// mapbox-gl sizes correctly. With a 60vw backdrop anchored to the right, the
// fade ramp lives roughly in [40vw, 60vw] — i.e. the fade is centered around
// the screen midpoint and the map is fully visible past ~60% across the page.
const FADE_MASK =
  "linear-gradient(90deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.4) 12%, rgba(0,0,0,0.85) 25%, rgba(0,0,0,1) 38%)";
const FADE_STYLE = {
  WebkitMaskImage: FADE_MASK,
  maskImage: FADE_MASK,
} as const;

export function AmbientBackdrop({ focus, arc = null }: AmbientBackdropProps) {
  return (
    <div className="pointer-events-none fixed inset-y-0 right-0 z-0 w-[60vw] overflow-hidden">
      {/* Map stays mounted across focus changes. When focus has no coords the
          map keeps its last camera position; only the marker is removed. */}
      <div className="absolute inset-0" style={FADE_STYLE}>
        <MapFlyer focus={focus} arc={arc} />
      </div>
    </div>
  );
}
