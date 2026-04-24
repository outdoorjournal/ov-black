"use client";

import { AnimatePresence, motion } from "framer-motion";

import { MapFlyer, type MapFocus } from "./MapFlyer";

interface AmbientBackdropProps {
  imageSrc: string | null;
  focus: MapFocus | null;
}

export function AmbientBackdrop({ imageSrc, focus }: AmbientBackdropProps) {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage: "linear-gradient(160deg, #101333 0%, #2a1b3c 55%, #3b2640 100%)",
        }}
      />
      <AnimatePresence mode="sync">
        {imageSrc ? (
          <motion.img
            key={imageSrc}
            src={imageSrc}
            alt=""
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.45 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.8 }}
            className="absolute inset-0 h-full w-full object-cover"
            style={{ filter: "blur(8px) saturate(0.85)" }}
          />
        ) : null}
      </AnimatePresence>
      <MapFlyer focus={focus} />
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(180deg, rgba(10,10,10,0) 40%, rgba(10,10,10,0.25) 100%)",
        }}
      />
    </div>
  );
}
