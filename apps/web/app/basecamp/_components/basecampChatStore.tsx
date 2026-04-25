"use client";

// Per-session zustand store for the basecamp chat surfaces. Trimmed parallel
// of apps/web/app/chat/[client_id]/_components/chatStore.tsx — no MoodBoard
// cards, but with two extras the basecamp UI needs:
//
//   - currentMood: the agent-driven ambience id, set on every `mood` SSE
//     frame from the agent. AtmosFrame consumes it and crossfades.
//   - commitAssistantSeed: synthesize a turn-0 assistant row from the seeded
//     opener. The basecamp single-prompt morph mounts ConversationStream
//     pre-populated with this turn so the opening line keeps DOM identity
//     across the (a) → (b) transition and stays put while the agent's
//     verbatim echo streams in.

import { fromSummary, type AgentTurnView, type StreamState } from "@/app/chat/[client_id]/_components/types";
import { createStoreContext } from "@/lib/store/createStoreContext";
import type { DoneFrame, ErrorFrame } from "@/lib/agentStream";
import type { AgentTurnSummary } from "@ov-black/api-client";
import type { MoodId } from "@/lib/atmos/moods";
import { DEFAULT_MOOD } from "@/lib/atmos/moods";

export type BasecampChatState = {
  turns: AgentTurnView[];
  streaming: StreamState | null;
  initialTurnsCount: number;
  currentMood: MoodId;
  commitUserTurn: (turn: AgentTurnView) => void;
  commitAssistantSeed: (content: string) => void;
  startStream: (turnIndex: number) => void;
  appendDelta: (text: string) => void;
  finishStream: (frame: DoneFrame) => void;
  errorStream: (frame: ErrorFrame) => void;
  setMood: (mood: MoodId) => void;
};

export type BasecampChatStoreInit = {
  initialTurns: AgentTurnSummary[];
  initialMood?: MoodId;
};

export function nextTurnIndex(turns: AgentTurnView[]): number {
  if (turns.length === 0) return 0;
  return turns[turns.length - 1]!.turn_index + 1;
}

export const basecampChatStore = createStoreContext<
  BasecampChatState,
  BasecampChatStoreInit
>(
  ({ initialTurns, initialMood }) =>
    (set) => ({
      turns: initialTurns.map(fromSummary),
      streaming: null,
      initialTurnsCount: initialTurns.length,
      currentMood: initialMood ?? DEFAULT_MOOD,
      commitUserTurn: (turn) =>
        set((s) => ({ turns: [...s.turns, turn] })),
      commitAssistantSeed: (content) =>
        set((s) => {
          const idx = nextTurnIndex(s.turns);
          const seed: AgentTurnView = {
            id: `seed-${idx}`,
            turn_index: idx,
            role: "assistant",
            content,
          };
          return { turns: [...s.turns, seed] };
        }),
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
      setMood: (mood) => set({ currentMood: mood }),
    }),
  "Basecamp",
);
