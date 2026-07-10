"use client";

// The client-side owner of the chat surface. Holds the zustand store that
// tracks the persisted turn list + the in-flight streaming buffer, wires
// the DIY SSE consumer (useAgentStream from T04) into the store, and
// auto-fires a craft-feel bootstrap turn on mount so the agent's opening
// move is what the user sees first — not a blank composer.
//
// The layout is deliberately split now so S06/S07 (mood board) can slide in
// later without another framing change: an absolute `atmos-frame` acts as
// the full-bleed backdrop, and a two-column grid carves out the conversation
// column (left) and an empty mood-board aside (right) that's ready to host
// imagery in a later slice.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  useAgentStream,
  type AgentNode,
  type CardFrame,
  type DeltaFrame,
  type DoneFrame,
  type ErrorFrame,
} from "@/lib/agentStream";
import { useAtmosOverride, usePhaseShiftMood } from "@/lib/atmos/classifier";
import { createBrowserSupabase } from "@/lib/supabase/client";

import { AtmosFrame } from "./AtmosFrame";
import type { CardActionKind } from "./Card";
import { chatStore, nextTurnIndex } from "./chatStore";
import { Composer } from "./Composer";
import { ConversationStream } from "./ConversationStream";
import { MoodBoard } from "./MoodBoard";
import type { InitialCardPayload } from "./types";
import {
  createApiClient,
  updateNodeStatus,
  type AgentTurnSummary,
  type NodeStatus,
} from "@ov-black/api-client";

// Craft-feel bootstrap: S04 enforces 1..8000 chars on /turn content, so an
// empty string is rejected at the API. A single space nudges the agent to
// open the correspondence itself (it references seeded Dossier facts in
// its greeting) without the user having to type a prompt first.
const BOOTSTRAP_CONTENT = " ";

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
  /** Shared app masthead, rendered above the immersive chat surface. */
  header?: ReactNode;
};

export function ChatShell({
  sessionId,
  accessToken,
  apiBaseUrl,
  client,
  initialTurns,
  itineraryId,
  initialCards = [],
  header = null,
}: ChatShellProps) {
  return (
    <chatStore.Provider initial={{ initialTurns, initialCards }}>
      <ChatShellInner
        sessionId={sessionId}
        accessToken={accessToken}
        apiBaseUrl={apiBaseUrl}
        client={client}
        itineraryId={itineraryId}
        header={header}
      />
    </chatStore.Provider>
  );
}

type ChatShellInnerProps = {
  sessionId: string;
  accessToken: string;
  apiBaseUrl: string;
  client: { id: string; full_name: string };
  itineraryId: string | undefined;
  header: ReactNode;
};

function ChatShellInner({
  sessionId,
  accessToken,
  apiBaseUrl,
  client,
  itineraryId,
  header,
}: ChatShellInnerProps) {
  const turns = chatStore.useStore((s) => s.turns);
  const streaming = chatStore.useStore((s) => s.streaming);
  const cards = chatStore.useStore((s) => s.cards);
  const initialTurnsCount = chatStore.useStore((s) => s.initialTurnsCount);
  const storeApi = chatStore.useStoreApi();

  const override = useAtmosOverride();
  const { mood: classifiedMood, phaseCounter } = usePhaseShiftMood(turns);
  const currentMood = override ?? classifiedMood;

  const abortRef = useRef<AbortController | null>(null);

  // True while the agent is off calling tools mid-turn — drives the map-fold
  // "working" indicator on the streaming row. Set by the anonymous `activity`
  // pulse, cleared by the next delta / done / error.
  const [working, setWorking] = useState(false);

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
    onActivity: () => {
      setWorking(true);
    },
    onDelta: (frame: DeltaFrame) => {
      setWorking(false);
      storeApi.getState().appendDelta(frame.text);
    },
    onDone: (frame: DoneFrame) => {
      setWorking(false);
      storeApi.getState().finishStream(frame);
    },
    onError: (frame: ErrorFrame) => {
      setWorking(false);
      storeApi.getState().errorStream(frame);
    },
    onCard: (frame: CardFrame) => {
      // Legacy path: pre-agent-workspace runtime. Persistence happens on
      // the API side; the frame already carries node_id + snapshot.
      storeApi.getState().proposeCard(frame);
    },
    onCardProposed: (node: AgentNode) => {
      // New path: apps/agent runtime. ``node`` is the persisted row from
      // POST /itinerary/{id}/nodes. Lift the snapshot out of metadata
      // and rebuild the legacy frame shape the store action handles.
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
      storeApi.getState().proposeCard(frame);
    },
    onNodeUpdated: (node: AgentNode) => {
      // Advisor adjustment landed — replay as a card-status flip. Known
      // statuses map cleanly; anything else is ignored (the status literal
      // must match NodeStatus in the api-client types).
      const allowed: readonly NodeStatus[] = [
        "pending",
        "approved",
        "booked",
        "confirmed",
        "discarded",
      ];
      if (allowed.includes(node.status as NodeStatus)) {
        storeApi.getState().setCardStatus(node.id, node.status as NodeStatus);
      }
    },
  });

  // MoodBoard card action handler. Pin → approved, Keep → pending (no-op
  // when already pending), Discard → discarded. Optimistic dispatch first,
  // then PATCH /itinerary/{id}/nodes/{id}; on non-ok we revert.
  const onCardAction = useCallback(
    (nodeId: string, action: CardActionKind) => {
      if (!itineraryId) return;
      const card = storeApi.getState().cards.find((c) => c.node_id === nodeId);
      if (!card) return;
      const nextStatus: NodeStatus =
        action === "pin"
          ? "approved"
          : action === "discard"
          ? "discarded"
          : "pending";
      if (card.status === nextStatus) return;
      const previousStatus = card.status;
      storeApi.getState().setCardStatus(nodeId, nextStatus);
      void (async () => {
        const token = await getAccessToken();
        if (!token) {
          storeApi.getState().revertCardStatus(nodeId, previousStatus);
          return;
        }
        const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
        const result = await updateNodeStatus(api, {
          itineraryId,
          nodeId,
          status: nextStatus,
        });
        if (!result.ok) {
          storeApi.getState().revertCardStatus(nodeId, previousStatus);
        }
      })();
    },
    [apiBaseUrl, getAccessToken, itineraryId, storeApi],
  );

  const submit = useCallback(
    (content: string, opts?: { hideUserTurn?: boolean }) => {
      const state = storeApi.getState();
      const optimisticIndex = nextTurnIndex(state.turns);
      // Optimistic user-turn row, unless this is the bootstrap (" ") call
      // where we don't want the user column to show a blank message.
      if (!opts?.hideUserTurn) {
        state.commitUserTurn({
          id: `user-${optimisticIndex}-${Date.now()}`,
          turn_index: optimisticIndex,
          role: "user",
          content,
        });
      }
      const assistantIndex = optimisticIndex + (opts?.hideUserTurn ? 0 : 1);
      storeApi.getState().startStream(assistantIndex);
      void sendTurn(content);
    },
    [sendTurn, storeApi],
  );

  useBootstrapOpener({
    initialTurnsCount,
    streaming,
    startStream: storeApi.getState().startStream,
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
    <div className="flex h-dvh flex-col">
      {header}
      <main
        className="relative min-h-0 flex-1"
        data-client-id={client.id}
        data-session-id={sessionId}
      >
        <AtmosFrame mood={currentMood} phaseCounter={phaseCounter} />
        <div className="relative grid h-full grid-cols-[1fr_minmax(0,480px)]">
          <div className="flex h-full min-h-0 flex-col">
            <header className="flex items-baseline justify-between border-b border-ink/10 px-8 pb-6 pt-8">
              <div>
                <p className="font-sans text-[11px] uppercase tracking-label text-ink/50">
                  Correspondence
                </p>
                <h1 className="mt-1 font-serif text-3xl text-ink">
                  {client.full_name}
                </h1>
              </div>
            </header>
            <ConversationStream turns={turns} streaming={streaming} working={working} />
            <Composer
              disabled={streaming !== null}
              onSend={(content) => submit(content)}
            />
          </div>
          <MoodBoard cards={cards} onAction={onCardAction} />
        </div>
      </main>
    </div>
  );
}

// Fires the auto-bootstrap turn exactly once when the session has no prior
// history. Split out as a hook so the effect's dependency list is isolated
// and we don't double-fire under React StrictMode's development-mode remount.
function useBootstrapOpener({
  initialTurnsCount,
  streaming,
  startStream,
  sendTurn,
}: {
  initialTurnsCount: number;
  streaming: { turnIndex: number; buffer: string } | null;
  startStream: (turnIndex: number) => void;
  sendTurn: (content: string) => Promise<void>;
}): void {
  const firedRef = useRef(false);

  useEffect(() => {
    if (firedRef.current) return;
    if (initialTurnsCount > 0) return;
    if (streaming !== null) return;
    firedRef.current = true;
    startStream(0);
    void sendTurn(BOOTSTRAP_CONTENT);
  }, [initialTurnsCount, streaming, startStream, sendTurn]);
}
