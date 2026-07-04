"use client";

// A self-contained agent conversation bound to one session `audience`. The
// itinerary view mounts two of these for an advisor:
//   - audience="advisor"  → a PRIVATE advisor<->AI workspace (the traveler is
//     never in it; the backend gates travelers out of this audience).
//   - audience="traveler" → the SHARED client conversation; the advisor posts
//     as staff and, with `hydrateHistory`, sees the traveler's prior turns.
//
// Each instance owns its own session id + message buffer + SSE turn loop, so
// the two conversations stay independent. They share ONE graph: a streamed
// `card_proposed` lands on the store's pendingProposals via proposeNode, the
// same surface the Build tools and the canvas read. Session open is lazy on
// first submit (idempotent per client_id+audience) unless `hydrateHistory`
// eagerly opens to replay history.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createApiClient,
  createSessionEndpoint,
  listTurns,
} from "@ov-black/api-client";

import { createBrowserSupabase } from "@/lib/supabase/client";
import { useAgentStream } from "@/lib/agentStream";

import {
  itineraryGraphStore,
  type ChatMessage,
} from "../../store/itineraryGraphStore";

import { ChatPanel } from "./ChatPanel";

type ConciergeChatProps = {
  audience: "traveler" | "advisor";
  apiBaseUrl: string | null;
  accessToken: string | null;
  clientId: string | null;
  itineraryId: string;
  /** Eagerly open the session on mount + replay prior turns (the client thread). */
  hydrateHistory?: boolean;
  /** Opening system line shown before any turns. */
  intro?: string;
  onScrollToNode?: (id: string) => void;
  /** Suppress ChatPanel's own header (a host provides one, e.g. the sheet). */
  hideHeader?: boolean;
  /** M006/PS2: bind to a SPECIFIC session (resume from the list) instead of
   *  lazily opening one. When set, no session is created — this thread streams
   *  onto the given id and hydrates its turns. */
  sessionId?: string;
  /** Called with the session id once this thread has one — whether passed in
   *  via `sessionId` or lazily created on the first turn. Lets a host (the
   *  concierge column) refresh its session list. */
  onSessionOpened?: (sessionId: string) => void;
};

export function ConciergeChat({
  audience,
  apiBaseUrl,
  accessToken,
  clientId,
  itineraryId,
  hydrateHistory = false,
  intro,
  onScrollToNode,
  hideHeader = false,
  sessionId,
  onSessionOpened,
}: ConciergeChatProps) {
  const pendingProposals = itineraryGraphStore.useStore(
    (s) => s.pendingProposals,
  );
  const storeApi = itineraryGraphStore.useStoreApi();
  const router = useRouter();

  const [messages, setMessages] = useState<ChatMessage[]>(
    intro
      ? [{ id: `${audience}-sys`, role: "system", text: intro }]
      : [],
  );
  const [streaming, setStreaming] = useState(false);

  // Seed from an explicit resume target (PS2) so ensureSession returns it
  // without ever creating a session.
  const sessionIdRef = useRef<string | null>(sessionId ?? null);
  const streamingIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);
  const canChat = Boolean(apiBaseUrl && accessToken && clientId);

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

  const appendDelta = useCallback((id: string, text: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text: m.text + text } : m)),
    );
  }, []);

  const { sendTurn } = useAgentStream({
    getSessionId: () => sessionIdRef.current,
    getAccessToken,
    apiBaseUrl: apiBaseUrl ?? "",
    abortRef,
    onDelta: (frame) => {
      const id = streamingIdRef.current;
      if (id) appendDelta(id, frame.text);
    },
    onDone: () => {
      const id = streamingIdRef.current;
      if (id) {
        setMessages((prev) =>
          prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
        );
      }
      streamingIdRef.current = null;
      setStreaming(false);
    },
    onError: () => {
      const id = streamingIdRef.current;
      if (id) {
        appendDelta(
          id,
          "\n\n(The concierge couldn’t respond just now. Try again in a moment.)",
        );
        setMessages((prev) =>
          prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
        );
      }
      streamingIdRef.current = null;
      setStreaming(false);
    },
    onCardProposed: (node) => {
      storeApi.getState().proposeNode({
        id: node.id,
        itinerary_id: node.itinerary_id,
        type: node.type,
        status: node.status,
        title: node.title,
        source: node.source ?? null,
        source_id: node.source_id ?? null,
        metadata: node.metadata ?? {},
      });
    },
    onNodeUpdated: (node) => {
      storeApi.getState().applyNodeUpdate({
        id: node.id,
        itinerary_id: node.itinerary_id,
        type: node.type,
        status: node.status,
        title: node.title,
        source: node.source ?? null,
        source_id: node.source_id ?? null,
        metadata: node.metadata ?? {},
      });
    },
    onItineraryUpdated: () => {
      // The trip's dates changed. Timing is server-rendered onto the timeline
      // prop (not the client store), so re-run the route's RSC to pull the
      // fresh window; the store's in-session graph state survives the refresh.
      router.refresh();
    },
  });

  // Open the session lazily, returning its id (or null on failure).
  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    if (!apiBaseUrl || !accessToken || !clientId) return null;
    const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
    const result = await createSessionEndpoint(api, {
      client_id: clientId,
      itinerary_id: itineraryId,
      audience,
    });
    if (!result.ok) return null;
    sessionIdRef.current = result.session_id;
    onSessionOpened?.(result.session_id);
    return result.session_id;
  }, [apiBaseUrl, accessToken, clientId, itineraryId, audience, onSessionOpened]);

  // Client thread: eagerly open + replay the traveler's prior turns so the
  // advisor joins an existing conversation rather than a blank one.
  useEffect(() => {
    if (!hydrateHistory || !canChat) return;
    let cancelled = false;
    void (async () => {
      const sid = await ensureSession();
      if (!sid || cancelled || !apiBaseUrl || !accessToken) return;
      const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const turns = await listTurns(api, sid);
      if (!turns.ok || cancelled) return;
      const hydrated: ChatMessage[] = turns.turns.map((t) => ({
        id: t.id,
        role:
          t.role === "user"
            ? "user"
            : t.role === "assistant"
              ? "assistant"
              : "system",
        text: t.content,
      }));
      setMessages((prev) => {
        const head = prev.filter((m) => m.role === "system" && m.id.endsWith("-sys"));
        return [...head, ...hydrated];
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrateHistory, canChat, ensureSession, apiBaseUrl, accessToken]);

  useEffect(() => {
    const ref = abortRef;
    return () => ref.current?.abort();
  }, []);

  const handleSubmit = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !canChat) return;
      // PS4: if a card scoped the concierge ("ask about this"), prefix the turn
      // so the reply is about that card, then clear the chip. Prefixing (not a
      // hidden field) keeps the scope visible in the transcript on resume.
      const ask = storeApi.getState().askContext;
      const turnText = ask ? `Regarding “${ask.title}”: ${trimmed}` : trimmed;
      if (ask) storeApi.getState().setAskContext(null);
      const n = (seqRef.current += 1);
      const userId = `${audience}-u-${n}`;
      const assistantId = `${audience}-a-${n}`;
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", text: turnText },
        { id: assistantId, role: "assistant", text: "", streaming: true },
      ]);
      streamingIdRef.current = assistantId;
      setStreaming(true);
      void (async () => {
        const sid = await ensureSession();
        if (!sid) {
          appendDelta(
            assistantId,
            "(Couldn’t reach the concierge. Try again in a moment.)",
          );
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, streaming: false } : m,
            ),
          );
          streamingIdRef.current = null;
          setStreaming(false);
          return;
        }
        await sendTurn(turnText);
      })();
    },
    [audience, canChat, ensureSession, appendDelta, sendTurn, storeApi],
  );

  return (
    <ChatPanel
      messages={messages}
      pendingProposals={pendingProposals}
      onAccept={(id) => storeApi.getState().acceptProposal(id)}
      onDismiss={(id) => storeApi.getState().dismissProposal(id)}
      onSubmit={handleSubmit}
      {...(onScrollToNode ? { onScrollToNode } : {})}
      disabled={!canChat || streaming}
      hideHeader={hideHeader}
    />
  );
}
