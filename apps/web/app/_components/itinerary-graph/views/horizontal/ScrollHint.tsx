"use client";

// "More-this-way" affordance. Shows on the left or right edge of the canvas
// viewport when there's still content to scroll into in that direction.
// Animates a gentle horizontal oscillation so the eye picks it up; clicking
// jumps the viewport by `scrollBy` pixels in that direction.
//
// Respects `prefers-reduced-motion`: oscillation is suppressed; the hint
// still fades in/out and stays clickable.

import { ChevronLeft, ChevronRight } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

interface ScrollHintProps {
  direction: "left" | "right";
  visible: boolean;
  onClick: () => void;
}

export function ScrollHint({ direction, visible, onClick }: ScrollHintProps) {
  const reduceMotion = useReducedMotion();
  const Icon = direction === "left" ? ChevronLeft : ChevronRight;
  // Oscillate ~5px toward the offscreen direction. easeInOut + 1.6s feels
  // alive without being twitchy; a faster cycle reads as urgency we don't
  // want here.
  const xKeyframes = reduceMotion
    ? 0
    : direction === "left"
    ? [0, -5, 0]
    : [0, 5, 0];
  const sideClass = direction === "left" ? "left-3" : "right-3";
  const ariaLabel = direction === "left" ? "Earlier days" : "Later days";

  return (
    <AnimatePresence>
      {visible ? (
        <motion.button
          type="button"
          onClick={onClick}
          aria-label={ariaLabel}
          className={[
            "pointer-events-auto absolute top-1/2 z-30 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-ink/15 bg-paper/90 text-ink/75 shadow-md backdrop-blur-xs hover:text-ink",
            sideClass,
          ].join(" ")}
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1, x: xKeyframes }}
          exit={{ opacity: 0, scale: 0.85 }}
          transition={{
            opacity: { duration: 0.18 },
            scale: { duration: 0.18 },
            x: reduceMotion
              ? { duration: 0 }
              : { repeat: Infinity, duration: 1.6, ease: "easeInOut" },
          }}
        >
          <Icon size={18} strokeWidth={1.8} aria-hidden />
        </motion.button>
      ) : null}
    </AnimatePresence>
  );
}
