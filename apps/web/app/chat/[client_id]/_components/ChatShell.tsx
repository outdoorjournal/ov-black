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
  useMemo,
  useReducer,
  useRef,
  type Dispatch,
} from "react";

import {
  useAgentStream,
  type AgentNode,
  type CardFrame,
  type DeltaFrame,
  type DoneFrame,
  type ErrorFrame,
} from "@/lib/agentStream";
import { useAtmosOverride, usePhaseShiftMood } from "@/lib/atmos/classifier";
import { createBrowserSupabase } from "@/lib/supabase";

import { AtmosFrame } from "./AtmosFrame";
import type { CardActionKind } from "./Card";
import { Composer } from "./Composer";
import { ConversationStream } from "./ConversationStream";
import { MoodBoard } from "./MoodBoard";
import {
  fromSummary,
  type AgentTurnView,
  type CardView,
  type InitialCardPayload,
  type StreamState,
} from "./types";
import {
  createApiClient,
  updateNodeStatus,
  type AgentTurnSummary,
  type NodeStatus,
} from "@ov-black/api-client";

// Craft-feel bootstrap: S04 enforces 1..8000 chars on /turn content, so an
// empty string is rejected at the API. A single space nudges the agent to
// open the correspondence itself (it references seeded Voodoo Doll facts in
// its greeting) without the user having to type a prompt first.
const BOOTSTRAP_CONTENT = " ";

type ShellState = {
  turns: AgentTurnView[];
  streaming: StreamState | null;
  cards: CardView[];
};

type ShellAction =
  | { type: "user_turn_committed"; turn: AgentTurnView }
  | { type: "stream_started"; turnIndex: number }
  | { type: "delta"; text: string }
  | { type: "done"; frame: DoneFrame }
  | { type: "error"; frame: ErrorFrame }
  | { type: "card_proposed"; frame: CardFrame }
  | { type: "card_action"; nodeId: string; nextStatus: NodeStatus }
  | { type: "card_action_reverted"; nodeId: string; previousStatus: NodeStatus };

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
      return { ...state, turns: [...state.turns, finalTurn], streaming: null };
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
      return { ...state, turns: [...state.turns, errorTurn], streaming: null };
    }
    case "card_proposed": {
      // Agent just emitted a `card` SSE frame. Append as `proposed`; if the
      // same node_id is re-emitted (shouldn't happen — T02 prompt avoids
      // re-proposing), the newer snapshot replaces the older one so the DOM
      // stays consistent with what the backend just persisted.
      const { frame } = action;
      const next: CardView = {
        node_id: frame.node_id,
        source: frame.source,
        source_id: frame.source_id,
        status: "proposed",
        snapshot: frame.snapshot,
      };
      const existingIndex = state.cards.findIndex(
        (c) => c.node_id === frame.node_id,
      );
      if (existingIndex === -1) {
        return { ...state, cards: [...state.cards, next] };
      }
      const cards = state.cards.slice();
      cards[existingIndex] = next;
      return { ...state, cards };
    }
    case "card_action": {
      return {
        ...state,
        cards: state.cards.map((c) =>
          c.node_id === action.nodeId ? { ...c, status: action.nextStatus } : c,
        ),
      };
    }
    case "card_action_reverted": {
      return {
        ...state,
        cards: state.cards.map((c) =>
          c.node_id === action.nodeId
            ? { ...c, status: action.previousStatus }
            : c,
        ),
      };
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
  // S07 T05: MoodBoard hydration on hard reload. Optional so older call sites
  // (and S05/S06 vitest suites) can omit it without breaking.
  itineraryId?: string;
  initialCards?: InitialCardPayload[];
};

export function ChatShell({
  sessionId,
  accessToken,
  apiBaseUrl,
  client,
  initialTurns,
  itineraryId,
  initialCards = [],
}: ChatShellProps) {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    turns: initialTurns.map(fromSummary),
    streaming: null,
    cards: initialCards.map((c) => ({
      node_id: c.node_id,
      source: c.source,
      source_id: c.source_id,
      status: c.status,
      snapshot: c.snapshot,
    })),
  }));

  const override = useAtmosOverride();
  const { mood: classifiedMood, phaseCounter } = usePhaseShiftMood(state.turns);
  const currentMood = override ?? classifiedMood;

  const abortRef = useRef<AbortController | null>(null);

  // Build a per-call token provider. The browser Supabase client is
  // configured by @supabase/ssr to auto-refresh the session, so its
  // getSession() returns a freshly-minted access token when the previous one
  // expired while the user was idle. We fall back to the initial SSR-passed
  // `accessToken` prop only when the browser client has no session at all —
  // that path is exercised by unit tests (jsdom, no NEXT_PUBLIC_ env) and by
  // a race window right after hydration before the session rehydrates.
  const getAccessToken = useMemo<() => Promise<string | null>>(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return async () => {
      if (supabase) {
        const {
          data: { session },
        } = await supabase.auth.getSession();
        if (session?.access_token) return session.access_token;
      }
      return accessToken ?? null;
    };
  }, [accessToken]);

  const { sendTurn } = useAgentStream({
    sessionId,
    getAccessToken,
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
    onCard: (frame: CardFrame) => {
      // Legacy path: pre-agent-workspace runtime. Persistence happens on
      // the API side; the frame already carries node_id + snapshot.
      dispatch({ type: "card_proposed", frame });
    },
    onCardProposed: (node: AgentNode) => {
      // New path: apps/agent runtime. ``node`` is the persisted row from
      // POST /itinerary/{id}/nodes. Lift the snapshot out of metadata
      // and rebuild the legacy frame shape the reducer already handles.
      const snapshot = (node.metadata?.snapshot ?? {
        title: node.title,
      }) as CardFrame["snapshot"];
      const frame: CardFrame = {
        type: "card",
        source: node.source ?? "",
        source_id: node.source_id ?? "",
        node_id: node.id,
        snapshot,
      };
      dispatch({ type: "card_proposed", frame });
    },
    onNodeUpdated: (node: AgentNode) => {
      // Advisor adjustment landed — replay as a card_action for the reducer.
      // Known statuses map cleanly; anything else is ignored (the status
      // literal must match NodeStatus in the api-client types).
      const allowed: readonly NodeStatus[] = [
        "idea",
        "proposed",
        "approved",
        "booked",
        "confirmed",
        "discarded",
      ];
      if (allowed.includes(node.status as NodeStatus)) {
        dispatch({
          type: "card_action",
          nodeId: node.id,
          nextStatus: node.status as NodeStatus,
        });
      }
    },
  });

  // MoodBoard card action handler. Pin → approved, Keep → proposed (no-op
  // when already proposed), Discard → discarded. Optimistic dispatch first,
  // then PATCH /itinerary/{id}/nodes/{id}; on non-ok we revert.
  const onCardAction = useCallback(
    (nodeId: string, action: CardActionKind) => {
      if (!itineraryId) return;
      const card = state.cards.find((c) => c.node_id === nodeId);
      if (!card) return;
      const nextStatus: NodeStatus =
        action === "pin"
          ? "approved"
          : action === "discard"
          ? "discarded"
          : "proposed";
      if (card.status === nextStatus) return;
      const previousStatus = card.status;
      dispatch({ type: "card_action", nodeId, nextStatus });
      void (async () => {
        const token = await getAccessToken();
        if (!token) {
          dispatch({ type: "card_action_reverted", nodeId, previousStatus });
          return;
        }
        const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
        const result = await updateNodeStatus(api, {
          itineraryId,
          nodeId,
          status: nextStatus,
        });
        if (!result.ok) {
          dispatch({ type: "card_action_reverted", nodeId, previousStatus });
        }
      })();
    },
    [apiBaseUrl, getAccessToken, itineraryId, state.cards],
  );

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
        <MoodBoard cards={state.cards} onAction={onCardAction} />
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
