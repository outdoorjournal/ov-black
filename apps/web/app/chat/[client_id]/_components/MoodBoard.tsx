"use client";

// The right-hand aside that hosts agent-proposed OV experience cards (S07 T05).
//
// Kept intentionally thin: consumes the reducer-held `cards` array from
// ChatShell and delegates every button to `onAction(nodeId, kind)`. Discarded
// cards are filtered out here so the fade is just a re-render, not an
// animation primitive — R014 says no spinners, skeletons, or motion beyond
// what the browser gives us for free.
//
// The aside carries BOTH `data-testid='mood-board-placeholder'` (back-compat
// with any earlier-slice assertions) and `data-testid='mood-board'` (the new
// selector T05 exposes) so we don't silently break a test while the old one
// lingers.

import { Card, type CardActionKind } from "./Card";
import type { CardView } from "./types";

export type MoodBoardProps = {
  cards: CardView[];
  onAction: (nodeId: string, action: CardActionKind) => void;
};

export function MoodBoard({ cards, onAction }: MoodBoardProps) {
  const visible = cards.filter((c) => c.status !== "discarded");

  return (
    <aside
      id="mood-board"
      className="h-full overflow-y-auto border-l border-ink/10 bg-paper/70"
      aria-label="Mood board"
      data-testid="mood-board"
    >
      <div
        className="flex flex-col gap-4 px-6 py-8"
        data-testid="mood-board-placeholder"
      >
        {visible.map((card) => (
          <Card
            key={card.node_id}
            card={card}
            onAction={(kind) => onAction(card.node_id, kind)}
          />
        ))}
      </div>
    </aside>
  );
}
