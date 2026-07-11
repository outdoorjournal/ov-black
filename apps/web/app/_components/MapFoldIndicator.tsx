"use client";

// "The concierge is working" indicator: a little road map folding and
// unfolding itself, shown in a streaming chat bubble while anonymous tool
// activity is in flight (the `activity` SSE frame). The frame deliberately
// carries no tool identity — this animation is all the disclosure there is.
//
// Look: four cream panels hinged in an accordion, a dotted route line running
// across them, and a single orange pin (restrained punctuation, per the design
// direction) marking the destination panel.

import { motion } from "framer-motion";

const PANELS = [0, 1, 2, 3];

// Dotted route line across each panel at mid-height.
const ROUTE_TEXTURE =
  "repeating-linear-gradient(90deg, rgba(20,18,14,0.35) 0 2px, transparent 2px 5px)";

export function MapFoldIndicator({
  label = "Checking my maps…",
}: {
  label?: string;
}) {
  return (
    <span
      role="status"
      aria-label={label}
      className="inline-flex items-center gap-2 align-middle"
    >
      <span className="inline-block" style={{ perspective: 140 }}>
        <span className="flex" style={{ transformStyle: "preserve-3d" }}>
          {PANELS.map((i) => {
            const foldsLeft = i % 2 === 0;
            return (
              <motion.span
                key={i}
                className="relative inline-block h-4 w-2.5 border border-ink/20 bg-paper"
                style={{
                  transformOrigin: foldsLeft ? "left center" : "right center",
                  backgroundImage: ROUTE_TEXTURE,
                  backgroundSize: "100% 1px",
                  backgroundPosition: "center 60%",
                  backgroundRepeat: "no-repeat",
                }}
                animate={{
                  rotateY: foldsLeft ? [0, -70, 0] : [0, 70, 0],
                  opacity: [1, 0.55, 1],
                }}
                transition={{
                  duration: 1.5,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: i * 0.14,
                }}
              >
                {i === 2 ? (
                  <span className="absolute right-[2px] top-[3px] h-1 w-1 rounded-full bg-[#F5701F]" />
                ) : null}
              </motion.span>
            );
          })}
        </span>
      </span>
      <span className="text-[11px] italic text-ink/55">{label}</span>
    </span>
  );
}
