"use client";

// Per-session zustand store for the client chat surface. Replaces the
// previous useReducer in ChatShell with action methods that mutate the same
// state shape. The store is scoped per chat-session via the Provider — a
// fresh session creates a fresh store, so navigating between clients does
// not bleed turn history or card state across instances.

import {
  cardFromNode,
  fromSummary,
  type AgentTurnView,
  type CardView,
  type InitialCardPayload,
  type StreamState,
} from "./types";
import { createStoreContext } from "@/lib/store/createStoreContext";
import type {
  CardFrame,
  DoneFrame,
  ErrorFrame,
} from "@/lib/agentStream";
import type {
  AgentTurnSummary,
  NodeStatus,
} from "@ov-black/api-client";

export type ChatState = {
  turns: AgentTurnView[];
  streaming: StreamState | null;
  cards: CardView[];
  // Stable count of turns at mount — used by the bootstrap-opener effect
  // (which must not re-fire when `turns` mutates after the user-turn commit).
  initialTurnsCount: number;
  commitUserTurn: (turn: AgentTurnView) => void;
  startStream: (turnIndex: number) => void;
  appendDelta: (text: string) => void;
  finishStream: (frame: DoneFrame) => void;
  errorStream: (frame: ErrorFrame) => void;
  proposeCard: (frame: CardFrame) => void;
  setCardStatus: (nodeId: string, nextStatus: NodeStatus) => void;
  revertCardStatus: (nodeId: string, previousStatus: NodeStatus) => void;
};

export type ChatStoreInit = {
  initialTurns: AgentTurnSummary[];
  initialCards: InitialCardPayload[];
};

export function nextTurnIndex(turns: AgentTurnView[]): number {
  if (turns.length === 0) return 0;
  return turns[turns.length - 1]!.turn_index + 1;
}

export const chatStore = createStoreContext<ChatState, ChatStoreInit>(
  ({ initialTurns, initialCards }) =>
    (set) => ({
      turns: initialTurns.map(fromSummary),
      streaming: null,
      cards: initialCards.map((c) => ({
        node_id: c.node_id,
        source: c.source,
        source_id: c.source_id,
        status: c.status,
        snapshot: c.snapshot,
      })),
      initialTurnsCount: initialTurns.length,
      commitUserTurn: (turn) =>
        set((s) => ({ turns: [...s.turns, turn] })),
      startStream: (turnIndex) =>
        set({ streaming: { turnIndex, buffer: "" } }),
      appendDelta: (text) =>
        set((s) =>
          s.streaming
            ? {
                streaming: {
                  ...s.streaming,
                  buffer: s.streaming.buffer + text,
                },
              }
            : s,
        ),
      finishStream: (frame) =>
        set((s) => {
          if (!s.streaming) return s;
          const finalTurn: AgentTurnView = {
            id: frame.turn_id,
            turn_index: s.streaming.turnIndex,
            role: "assistant",
            content: s.streaming.buffer,
          };
          return { turns: [...s.turns, finalTurn], streaming: null };
        }),
      errorStream: (frame) =>
        set((s) => {
          const index = s.streaming?.turnIndex ?? nextTurnIndex(s.turns);
          const errorTurn: AgentTurnView = {
            id: `error-${index}-${Date.now()}`,
            turn_index: index,
            role: "error",
            content: frame.reason,
          };
          return { turns: [...s.turns, errorTurn], streaming: null };
        }),
      proposeCard: (frame) =>
        set((s) => {
          const next: CardView = {
            node_id: frame.node_id,
            source: frame.source,
            source_id: frame.source_id,
            status: "pending",
            snapshot: frame.snapshot,
          };
          const idx = s.cards.findIndex((c) => c.node_id === frame.node_id);
          if (idx === -1) return { cards: [...s.cards, next] };
          const cards = s.cards.slice();
          cards[idx] = next;
          return { cards };
        }),
      setCardStatus: (nodeId, nextStatus) =>
        set((s) => ({
          cards: s.cards.map((c) =>
            c.node_id === nodeId ? { ...c, status: nextStatus } : c,
          ),
        })),
      revertCardStatus: (nodeId, previousStatus) =>
        set((s) => ({
          cards: s.cards.map((c) =>
            c.node_id === nodeId ? { ...c, status: previousStatus } : c,
          ),
        })),
    }),
  "Chat",
);

// Re-export so downstream files don't need to import the types module.
export { cardFromNode };
