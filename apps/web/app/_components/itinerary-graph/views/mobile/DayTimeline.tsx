"use client";

// One day's worth of the itinerary as a vertical, scrollable feed of cards.
// Reuses the same NodeCard the desktop canvas draws, so a card looks identical
// across surfaces. The card column is centered at the design system's fixed
// card width; the bottom padding clears the peeked concierge sheet.

import { NodeCard } from "../horizontal/NodeCard";
import type { DayGroup } from "../../shared/groupNodesByDay";

interface DayTimelineProps {
  group: DayGroup;
  tzOffsetHours: number;
  flashNodeId: string | null;
  onCardClick: (id: string) => void;
}

export function DayTimeline({
  group,
  tzOffsetHours,
  flashNodeId,
  onCardClick,
}: DayTimelineProps) {
  if (group.items.length === 0) {
    return (
      <div className="px-6 py-16 text-center font-serif text-[14px] italic text-ink/45">
        Nothing planned for {group.label} yet.
        <div className="mt-1 font-sans text-[11px] not-italic text-ink/40">
          Ask the concierge below for an idea.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-[260px] flex-col gap-3 px-0 py-4 pb-28">
      {group.items.map((node) => (
        <NodeCard
          key={node.id}
          node={node}
          tzOffsetHours={tzOffsetHours}
          flash={flashNodeId === node.id}
          onClick={() => onCardClick(node.id)}
        />
      ))}
    </div>
  );
}
