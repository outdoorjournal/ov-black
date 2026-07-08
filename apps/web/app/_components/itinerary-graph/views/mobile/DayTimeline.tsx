"use client";

// One day's worth of the itinerary as a vertical, scrollable feed of cards.
// Reuses the same NodeCard the desktop canvas draws, so a card looks identical
// across surfaces. The card column is centered at the design system's fixed
// card width; the bottom padding clears the peeked concierge sheet.

import { NodeCard } from "../horizontal/NodeCard";
import type { BillingChip } from "@/app/itinerary/[id]/_shell/dashboardModel";
import { NotesPanel } from "../../shared/NotesPanel";
import type { DayGroup } from "../../shared/groupNodesByDay";
import type { NodeResponse } from "../../model/horizontalTypes";

interface DayTimelineProps {
  group: DayGroup;
  tzOffsetHours: number;
  flashNodeId: string | null;
  onCardClick: (id: string) => void;
  // Host node id → attached `note` nodes, for the per-card note badge.
  attachedNotes?: Map<string, NodeResponse[]>;
  // When set, a per-day composer lets the traveler drop a free-standing note
  // ("a dinner between these") on this day for staff to act on.
  canLeaveNote?: boolean;
  onAddDayNote?: (dayKey: string, text: string) => void;
  // ADV-15: node id → its billing chip (advisor surfaces; absent → no chips).
  billingChips?: Record<string, BillingChip>;
}

export function DayTimeline({
  group,
  tzOffsetHours,
  flashNodeId,
  onCardClick,
  attachedNotes,
  canLeaveNote = false,
  onAddDayNote,
  billingChips,
}: DayTimelineProps) {
  const dayComposer =
    canLeaveNote && onAddDayNote ? (
      <div className="mx-auto w-[260px]">
        <NotesPanel
          notes={[]}
          canAdd
          onAddNote={(text) => onAddDayNote(group.date, text)}
        />
      </div>
    ) : null;

  if (group.items.length === 0) {
    return (
      <div className="px-6 py-16 text-center">
        <div className="font-serif text-[14px] italic text-ink/45">
          Nothing planned for {group.label} yet.
        </div>
        <div className="mt-1 font-sans text-[11px] text-ink/40">
          Ask the concierge below for an idea.
        </div>
        <div className="mt-4 text-left">{dayComposer}</div>
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
          attachedNoteCount={attachedNotes?.get(node.id)?.length ?? 0}
          billingChip={billingChips?.[node.id] ?? null}
        />
      ))}
      {dayComposer}
    </div>
  );
}
