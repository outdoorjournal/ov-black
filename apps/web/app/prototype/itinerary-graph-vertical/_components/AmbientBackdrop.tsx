"use client";

import { AnimatePresence, motion } from "framer-motion";

import { MapFlyer, type MapFocus } from "./MapFlyer";

interface AmbientBackdropProps {
  imageSrc: string | null;
  focus: MapFocus | null;
}

// Alpha mask: transparent on the left, opaque on the right. Applied to the
// *visual* layers (map + image) only, so the parent keeps its dimensions and
// mapbox-gl sizes correctly.
const FADE_MASK =
  "linear-gradient(90deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.15) 18%, rgba(0,0,0,0.7) 40%, rgba(0,0,0,0.95) 60%, rgba(0,0,0,1) 75%)";
const FADE_STYLE = {
  WebkitMaskImage: FADE_MASK,
  maskImage: FADE_MASK,
} as const;

export function AmbientBackdrop({ imageSrc, focus }: AmbientBackdropProps) {
  const showMap = Boolean(focus);
  return (
    <div className="pointer-events-none fixed inset-y-0 right-0 z-0 w-1/2 overflow-hidden">
      {/* Map always mounted (avoids tear-down), shown only when focus has coords. */}
      <div
        className="absolute inset-0 transition-opacity duration-700"
        style={{ opacity: showMap ? 1 : 0, ...FADE_STYLE }}
      >
        <MapFlyer focus={focus} />
      </div>

      {/* Fallback imagery only when no coords. */}
      <AnimatePresence mode="sync">
        {!showMap && imageSrc ? (
          <motion.img
            key={imageSrc}
            src={imageSrc}
            alt=""
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.6 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.8 }}
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter: "blur(6px) saturate(0.9)", ...FADE_STYLE }}
          />
        ) : null}
      </AnimatePresence>
    </div>
  );
}
