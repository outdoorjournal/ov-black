"use client";

import { motion } from "framer-motion";

import type { MoodId, NodeResponse } from "@/app/_components/itinerary-graph/model/baseTypes";
import { Card } from "@/app/_components/itinerary-graph/shared/ExpandedCard";

interface GhostCardProps {
  node: NodeResponse;
  mood: MoodId;
  onAccept: () => void;
  onDismiss: () => void;
  onClick?: () => void;
}

export function GhostCard({
  node,
  mood,
  onAccept,
  onDismiss,
  onClick,
}: GhostCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.35 }}
      className="relative"
    >
      <Card node={node} mood={mood} {...(onClick ? { onClick } : {})} ghost />
      <div className="mt-1.5 flex gap-1.5 px-0.5">
        <button
          type="button"
          onClick={onAccept}
          className="flex-1 rounded-md bg-ink px-2 py-1 text-[11px] uppercase tracking-[0.18em] text-paper transition hover:opacity-90"
        >
          Accept
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-md border border-ink/20 px-2 py-1 text-[11px] uppercase tracking-[0.18em] text-ink/70 transition hover:bg-ink/5"
        >
          Dismiss
        </button>
      </div>
    </motion.div>
  );
}
