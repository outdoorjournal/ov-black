"use client";

// "The concierge is working" indicator: a little folded road map with a compass
// tucked in its lower-right corner, its needle wandering as it hunts for a
// bearing. Shown in a streaming chat bubble while anonymous tool activity is in
// flight (the `activity` SSE frame). The frame deliberately carries no tool
// identity — this animation is all the disclosure there is.
//
// Look: a cream map panel creased into folds with a dotted route and one orange
// destination pin (restrained punctuation, per the design direction), and a
// compass badge overhanging the corner whose orange-tipped needle sweeps around
// searching before it settles — then searches again.

import { motion } from "framer-motion";

const BRAND = "#F5701F";

// The needle "hunting" for a bearing: it swings past, backs off, overshoots the
// other way, and keeps casting about — never quite settling. easeInOut on each
// leg gives the swings weight, like a real magnetized needle.
const NEEDLE_SWEEP = [0, 140, 80, 255, 200, 330, 25, 0];

export function MapCompassIndicator({
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
      <svg
        width={40}
        height={28}
        viewBox="0 0 40 28"
        fill="none"
        aria-hidden="true"
        className="inline-block shrink-0"
      >
        {/* Map panel */}
        <rect
          x={1.5}
          y={1.5}
          width={29}
          height={22}
          rx={1}
          className="fill-paper stroke-ink/25"
          strokeWidth={0.8}
        />
        {/* Fold creases */}
        <g className="stroke-ink/10" strokeWidth={0.6}>
          <line x1={11} y1={1.5} x2={11} y2={23.5} />
          <line x1={20.5} y1={1.5} x2={20.5} y2={23.5} />
          <line x1={1.5} y1={12.5} x2={30.5} y2={12.5} />
        </g>
        {/* Dotted route */}
        <path
          d="M5 18 Q 13 16.5 15.5 11.5 T 23 6"
          className="stroke-ink/40"
          strokeWidth={0.9}
          strokeLinecap="round"
          strokeDasharray="0.5 2.4"
        />
        {/* Destination pin */}
        <circle cx={23} cy={6} r={1.7} fill={BRAND} />
        <circle cx={23} cy={6} r={3} fill={BRAND} opacity={0.2} />

        {/* Compass badge, overhanging the lower-right corner */}
        <g>
          <circle
            cx={30}
            cy={21}
            r={6.4}
            className="fill-white stroke-ink/30"
            strokeWidth={0.8}
          />
          <circle
            cx={30}
            cy={21}
            r={4.7}
            className="stroke-ink/12"
            strokeWidth={0.6}
          />
          {/* Cardinal ticks */}
          <g className="stroke-ink/25" strokeWidth={0.7} strokeLinecap="round">
            <line x1={30} y1={15.4} x2={30} y2={16.4} />
            <line x1={30} y1={25.6} x2={30} y2={26.6} />
            <line x1={24.4} y1={21} x2={25.4} y2={21} />
            <line x1={34.6} y1={21} x2={35.6} y2={21} />
          </g>
          {/* Sweeping needle */}
          <motion.g
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
            animate={{ rotate: NEEDLE_SWEEP }}
            transition={{
              duration: 4.2,
              repeat: Infinity,
              ease: "easeInOut",
              times: [0, 0.16, 0.3, 0.46, 0.62, 0.78, 0.92, 1],
            }}
          >
            {/* North half (orange) */}
            <polygon points="30,16.6 30.85,21 29.15,21" fill={BRAND} />
            {/* South half (ink) */}
            <polygon points="30,25.4 30.85,21 29.15,21" className="fill-ink/55" />
          </motion.g>
          {/* Hub */}
          <circle
            cx={30}
            cy={21}
            r={0.9}
            className="fill-paper stroke-ink/40"
            strokeWidth={0.5}
          />
        </g>
      </svg>
      <span className="text-[11px] italic text-ink/55">{label}</span>
    </span>
  );
}
