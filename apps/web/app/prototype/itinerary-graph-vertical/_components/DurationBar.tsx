"use client";

import type { NodeType } from "@/app/_components/itinerary-graph/model/types";
import { formatDuration } from "@/app/_components/itinerary-graph/model/time";

interface DurationBarProps {
  type: NodeType;
  barH: number;
  durationMinutes: number;
}

const TYPE_COLOR: Record<NodeType, string> = {
  flight: "#4d7490",
  transit: "#7a7a7a",
  subway: "#7a7a7a",
  train: "#7a7a7a",
  drive: "#7a7a7a",
  walk: "#7a7a7a",
  boat: "#4d7490",
  experience: "#b58a3a",
  destination: "#5f7a4a",
  hotel: "#3a3a3a",
  meal: "#b85a3e",
  free_time: "#a0a0a0",
  waiting: "#a0a0a0",
  note: "#bbb6ad",
};

export function DurationBar({ type, barH, durationMinutes }: DurationBarProps) {
  const color = TYPE_COLOR[type];
  const showLabel = barH > 64 && durationMinutes >= 60;
  return (
    <div
      aria-hidden
      className="absolute left-0 top-0 rounded-full"
      style={{
        width: 4,
        height: barH,
        backgroundColor: color,
        opacity: 0.55,
        boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.15)",
      }}
    >
      {showLabel ? (
        <span
          className="absolute left-3 bottom-1 text-[10px] uppercase tracking-[0.14em]"
          style={{ color: color, opacity: 0.8 }}
        >
          {formatDuration(durationMinutes)}
        </span>
      ) : null}
    </div>
  );
}
