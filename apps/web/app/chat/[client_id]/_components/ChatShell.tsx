"use client";

// The client-side owner of the chat surface. Holds the reducer that tracks
// the persisted turn list + the in-flight streaming buffer, wires the DIY
// SSE consumer (useAgentStream from T04) into the reducer, and auto-fires a
// craft-feel bootstrap turn on mount so the agent's opening move is what the
// user sees first — not a blank composer.
//
// The layout is deliberately split now so S06/S07 (mood board) can slide in
// later without another framing change: an absolute `atmos-frame` acts as
// the full-bleed backdrop, and a two-column grid carves out the conversation
// column (left) and an empty mood-board aside (right) that's ready to host
// imagery in a later slice.

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  type Dispatch,
} from "react";

import { useAgentStream, type DeltaFrame, type DoneFrame, type ErrorFrame } from "@/lib/agentStream";
import { useAtmosOverride, usePhaseShiftMood } from "@/lib/atmos/classifier";

import { AtmosFrame } from "./AtmosFrame";
import { Composer } from "./Composer";
import { ConversationStream } from "./ConversationStream";
import { fromSummary, type AgentTurnView, type StreamState } from "./types";
import type { AgentTurnSummary } from "@ov-black/api-client";

// Craft-feel bootstrap: S04 enforces 1..8000 chars on /turn content, so an
// empty string is rejected at the API. A single space nudges the agent to
// open the correspondence itself (it references seeded Voodoo Doll facts in
// its greeting) without the user having to type a prompt first.
const BOOTSTRAP_CONTENT = " ";

type ShellState = {
  turns: AgentTurnView[];
  streaming: StreamState | null;
};

type ShellAction =
  | { type: "user_turn_committed"; turn: AgentTurnView }
  | { type: "stream_started"; turnIndex: number }
  | { type: "delta"; text: string }
  | { type: "done"; frame: DoneFrame }
  | { type: "error"; frame: ErrorFrame };

function reducer(state: ShellState, action: ShellAction): ShellState {
  switch (action.type) {
    case "user_turn_committed":
      return { ...state, turns: [...state.turns, action.turn] };
    case "stream_started":
      return {
        ...state,
        streaming: { turnIndex: action.turnIndex, buffer: "" },
      };
    case "delta": {
      if (!state.streaming) return state;
      return {
        ...state,
        streaming: {
          ...state.streaming,
          buffer: state.streaming.buffer + action.text,
        },
      };
    }
    case "done": {
      if (!state.streaming) return state;
      const finalTurn: AgentTurnView = {
        id: action.frame.turn_id,
        turn_index: state.streaming.turnIndex,
        role: "assistant",
        content: state.streaming.buffer,
      };
      return { turns: [...state.turns, finalTurn], streaming: null };
    }
    case "error": {
      const index = state.streaming?.turnIndex ?? nextTurnIndex(state.turns);
      const errorTurn: AgentTurnView = {
        id: `error-${index}-${Date.now()}`,
        turn_index: index,
        role: "error",
        // content isn't rendered — the ConversationStream row uses the
        // D015 literal fallback copy instead. We still store the backend
        // `reason` verbatim for debugging/network-tab correlation.
        content: action.frame.reason,
      };
      return { turns: [...state.turns, errorTurn], streaming: null };
    }
    default:
      return state;
  }
}

function nextTurnIndex(turns: AgentTurnView[]): number {
  if (turns.length === 0) return 0;
  return turns[turns.length - 1]!.turn_index + 1;
}

export type ChatShellProps = {
  sessionId: string;
  accessToken: string;
  apiBaseUrl: string;
  client: { id: string; full_name: string };
  initialTurns: AgentTurnSummary[];
};

export function ChatShell({
  sessionId,
  accessToken,
  apiBaseUrl,
  client,
  initialTurns,
}: ChatShellProps) {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    turns: initialTurns.map(fromSummary),
    streaming: null,
  }));

  const override = useAtmosOverride();
  const { mood: classifiedMood, phaseCounter } = usePhaseShiftMood(state.turns);
  const currentMood = override ?? classifiedMood;

  const abortRef = useRef<AbortController | null>(null);

  const { sendTurn } = useAgentStream({
    sessionId,
    accessToken,
    apiBaseUrl,
    abortRef,
    onFirstToken: () => {
      // first_token arrival is observable via the streaming row appearing
      // in the DOM; no dedicated callback work needed here.
    },
    onDelta: (frame: DeltaFrame) => {
      dispatch({ type: "delta", text: frame.text });
    },
    onDone: (frame: DoneFrame) => {
      dispatch({ type: "done", frame });
    },
    onError: (frame: ErrorFrame) => {
      dispatch({ type: "error", frame });
    },
  });

  const submit = useCallback(
    (content: string, opts?: { hideUserTurn?: boolean }) => {
      // Optimistic user-turn row, unless this is the bootstrap (" ") call
      // where we don't want the user column to show a blank message.
      if (!opts?.hideUserTurn) {
        const optimisticIndex = nextTurnIndex(state.turns);
        dispatch({
          type: "user_turn_committed",
          turn: {
            id: `user-${optimisticIndex}-${Date.now()}`,
            turn_index: optimisticIndex,
            role: "user",
            content,
          },
        });
      }
      const assistantIndex = nextTurnIndex(state.turns) + (opts?.hideUserTurn ? 0 : 1);
      dispatch({ type: "stream_started", turnIndex: assistantIndex });
      void sendTurn(content);
    },
    [sendTurn, state.turns],
  );

  useBootstrapOpener({
    initialTurnsCount: initialTurns.length,
    streaming: state.streaming,
    dispatch,
    sendTurn,
  });

  // Cancel any in-flight stream on unmount so the fetch reader doesn't leak.
  // We capture the ref itself (not .current) because the ref object is stable
  // for the component's lifetime — we want to read whatever .current holds
  // at unmount time, not the current-at-mount value.
  useEffect(() => {
    const ref = abortRef;
    return () => {
      ref.current?.abort();
    };
  }, []);

  return (
    <main
      className="relative min-h-screen"
      data-client-id={client.id}
      data-session-id={sessionId}
    >
      <AtmosFrame mood={currentMood} phaseCounter={phaseCounter} />
      <div className="relative grid min-h-screen grid-cols-[1fr_minmax(0,480px)]">
        <div className="flex min-h-screen flex-col">
          <header className="flex items-baseline justify-between border-b border-ink/10 px-8 pb-6 pt-8">
            <div>
              <p className="font-sans text-[11px] uppercase tracking-[0.3em] text-ink/50">
                Correspondence
              </p>
              <h1 className="mt-1 font-serif text-3xl text-ink">
                {client.full_name}
              </h1>
            </div>
          </header>
          <ConversationStream turns={state.turns} streaming={state.streaming} />
          <Composer
            disabled={state.streaming !== null}
            onSend={(content) => submit(content)}
          />
        </div>
        <aside
          id="mood-board"
          className="border-l border-ink/10 bg-paper/70"
          aria-label="Mood board"
          data-testid="mood-board-placeholder"
        />
      </div>
    </main>
  );
}

// Fires the auto-bootstrap turn exactly once when the session has no prior
// history. Split out as a hook so the effect's dependency list is isolated
// and we don't double-fire under React StrictMode's development-mode remount.
function useBootstrapOpener({
  initialTurnsCount,
  streaming,
  dispatch,
  sendTurn,
}: {
  initialTurnsCount: number;
  streaming: StreamState | null;
  dispatch: Dispatch<ShellAction>;
  sendTurn: (content: string) => Promise<void>;
}): void {
  const firedRef = useRef(false);

  useEffect(() => {
    if (firedRef.current) return;
    if (initialTurnsCount > 0) return;
    if (streaming !== null) return;
    firedRef.current = true;
    dispatch({ type: "stream_started", turnIndex: 0 });
    void sendTurn(BOOTSTRAP_CONTENT);
    // sendTurn identity is stable (T04 holds options in a ref), so we can
    // omit it from deps without lint churn — but include it defensively so
    // react-hooks/exhaustive-deps stays quiet.
  }, [initialTurnsCount, streaming, dispatch, sendTurn]);
}
