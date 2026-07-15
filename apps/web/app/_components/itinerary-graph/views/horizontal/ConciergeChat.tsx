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
  campaignKickoff,
  createApiClient,
  createSessionEndpoint,
  listTurns,
  type NodeResponse,
} from "@ov-black/api-client";

import { createBrowserSupabase } from "@/lib/supabase/client";
import { useAgentStream } from "@/lib/agentStream";

import { prefersReducedMotion, scrollBehaviorFor } from "../journal/motion";

import {
  itineraryGraphStore,
  type ChatMessage,
} from "../../store/itineraryGraphStore";

import { ConversationPanel } from "@/app/_components/concierge/ConversationPanel";
import { AgentSurface } from "@/app/_components/concierge/surfaces/AgentSurface";
import {
  ArticleResolverContext,
  SurfaceContext,
} from "@/app/_components/concierge/surfaces/SurfaceContext";
import type {
  ArticleSurfaceView,
  OptionView,
} from "@/app/_components/concierge/surfaces/types";
import {
  optionReply,
  useAgentSurface,
} from "@/app/_components/concierge/surfaces/useAgentSurface";

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
  /** Which side of this chat the drawer flyout emerges toward. Defaults to
   *  "left" (the HorizontalView prototype's right-hand aside); the routed
   *  shell's ConciergeColumn sits on the LEFT, so it passes "right". */
  surfaceSide?: "left" | "right";
  /** Campaign dashboard: on mount, DETERMINISTICALLY lay down the curated spine
   *  (POST /campaign/kickoff), stream its cards in with the staggered reveal,
   *  then fire ONE agent opener turn that greets the trip and asks about the
   *  gaps (dates / party / the way in). The caller only sets this at the right
   *  moment (traveler's own campaign trip, empty graph); fired at most once. */
  autoKickoff?: boolean;
};

/** Gap between staggered card reveals when a server-built batch (the campaign
 *  spine) streams in — snappy, ~1.5s for a 7-night spine. */
const REVEAL_STAGGER_MS = 90;

/** Turn a reading-list `article` node into the flyout's view, or null when it
 *  isn't a usable read. Mirrors the metadata shape `add_article_to_reading_list`
 *  writes (`snapshot` + `url` + `publication`) — the same source
 *  `readingItem.toReadingItem` reads — so an `article:` chip opens the same
 *  piece the Reading rack shows. */
function articleViewFromNode(node: NodeResponse | undefined): ArticleSurfaceView | null {
  if (!node || node.type !== "article") return null;
  const meta = node.metadata ?? {};
  const rawSnap = meta["snapshot"];
  const snap: Record<string, unknown> =
    rawSnap && typeof rawSnap === "object" ? (rawSnap as Record<string, unknown>) : {};

  const str = (v: unknown): string | undefined =>
    typeof v === "string" && v.length > 0 ? v : undefined;
  const num = (v: unknown): number | undefined =>
    typeof v === "number" && Number.isFinite(v) ? v : undefined;

  const title = str(snap["title"]) ?? str(node.title);
  const url = str(meta["url"]) ?? str(snap["url"]);
  if (!title || !url) return null;

  const publication = str(meta["publication"]);
  const ogImage = str(snap["cover_image"]);
  const excerpt = str(snap["description"]);
  const readingTimeMinutes = num(meta["reading_time_minutes"]);
  return {
    title,
    url,
    ...(publication ? { publication } : {}),
    ...(ogImage ? { ogImage } : {}),
    ...(excerpt ? { excerpt } : {}),
    ...(readingTimeMinutes !== undefined ? { readingTimeMinutes } : {}),
  };
}

// Scroll a just-accepted card into view. It lands in the store synchronously,
// but its day section on the spine may only appear after the server timeline
// scaffold rebuilds (router.refresh), so retry a few frames until the element
// mounts rather than firing once and missing it. Timers are parked on the
// caller's reveal-timer ref so unmount cancels any still pending.
function scrollNodeIntoView(
  nodeId: string,
  timersRef: { current: ReturnType<typeof setTimeout>[] },
) {
  if (typeof document === "undefined") return;
  let tries = 0;
  const attempt = () => {
    const el = document.querySelector<HTMLElement>(
      `[data-node-id="${nodeId}"]`,
    );
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({
        behavior: scrollBehaviorFor(prefersReducedMotion()),
        block: "center",
      });
      return;
    }
    if (tries++ < 8) timersRef.current.push(setTimeout(attempt, 100));
  };
  timersRef.current.push(setTimeout(attempt, 60));
}

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
  surfaceSide = "left",
  autoKickoff = false,
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
  // True while the agent is off calling tools and hasn't streamed text yet —
  // drives the map-fold "working" indicator in the streaming bubble. Set by
  // the anonymous `activity` pulse, cleared by the next delta / done / error.
  const [working, setWorking] = useState(false);

  // Seed from an explicit resume target (PS2) so ensureSession returns it
  // without ever creating a session.
  const sessionIdRef = useRef<string | null>(sessionId ?? null);
  const streamingIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The drawer flyout anchors here and slides out toward `surfaceSide`,
  // over whatever sits beside this chat.
  const panelRef = useRef<HTMLDivElement | null>(null);
  const seqRef = useRef(0);
  // Snappy staggered reveal of a server-built batch (the campaign spine): the
  // nodes arrive in one burst, so space their drops ~90ms apart for the
  // "cards appearing" effect instead of a single pop. `revealCountRef` indexes
  // the current burst (reset each turn on `done`); `revealTimersRef` holds the
  // pending timers so they can be cancelled on unmount.
  const revealCountRef = useRef(0);
  const revealTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
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

  // The drawer over this aside — agent-pushed panels (route brochure,
  // decision cards) and chip-opened place briefs share one host.
  const { surface, onSurface, opener, close } = useAgentSurface();

  const { sendTurn } = useAgentStream({
    getSessionId: () => sessionIdRef.current,
    getAccessToken,
    apiBaseUrl: apiBaseUrl ?? "",
    abortRef,
    onSurface,
    onActivity: () => {
      if (streamingIdRef.current) setWorking(true);
    },
    onDelta: (frame) => {
      setWorking(false);
      const id = streamingIdRef.current;
      if (id) appendDelta(id, frame.text);
    },
    onDone: () => {
      setWorking(false);
      // How many nodes the agent BUILT this turn (campaign spine / from-inventory
      // writes). Capture before the reset below.
      const revealBurst = revealCountRef.current;
      // Next turn's reveal burst starts fresh.
      revealCountRef.current = 0;
      const id = streamingIdRef.current;
      if (id) {
        setMessages((prev) =>
          prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
        );
      }
      streamingIdRef.current = null;
      setStreaming(false);
      // Nodes the agent built server-side land in the client store immediately
      // (so the canvas reveals them), but the day scaffold — which groups cards
      // into dated days — is server-rendered onto the timeline prop and does NOT
      // re-derive from the store. On a trip whose dates the spine itself
      // established (e.g. an empty campaign shell at kickoff), the stale scaffold
      // has no bucket for the new dates, so the journal shows "an open day" until
      // a reload. Re-run the route's RSC once the reveal burst has settled so the
      // scaffold rebuilds from the fresh graph. Same mechanism as
      // onItineraryUpdated; the store's in-session state survives the refresh.
      if (revealBurst > 0) {
        const timer = setTimeout(
          () => router.refresh(),
          revealBurst * REVEAL_STAGGER_MS + REVEAL_STAGGER_MS,
        );
        revealTimersRef.current.push(timer);
      }
    },
    onError: () => {
      setWorking(false);
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
    onNodeCreated: (node) => {
      // A node the agent BUILT server-side (campaign spine) — drop it straight
      // onto the canvas, no accept step. Stagger the burst for the reveal.
      const payload = {
        id: node.id,
        itinerary_id: node.itinerary_id,
        parent_subgraph_id: node.parent_subgraph_id ?? null,
        type: node.type,
        status: node.status,
        title: node.title,
        source: node.source ?? null,
        source_id: node.source_id ?? null,
        metadata: node.metadata ?? {},
      };
      const delay = revealCountRef.current * REVEAL_STAGGER_MS;
      revealCountRef.current += 1;
      const timer = setTimeout(() => {
        storeApi.getState().insertCreatedNode(payload);
      }, delay);
      revealTimersRef.current.push(timer);
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
    // The agent changed the travel party — a new/updated member
    // (`party_updated`) or an existing member seated/unseated on this trip
    // (`party_changed`). The roster is a client-side fetch (not a server prop),
    // so `router.refresh()` can't re-run it; bump the store nonce that the
    // dashboard's party fetch keys off so the hero chip re-reads.
    onPartyUpdated: () => {
      storeApi.getState().bumpPartyRevision();
    },
    onPartyChanged: () => {
      storeApi.getState().bumpPartyRevision();
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
              : t.role === "error"
                ? "error"
                : "system",
        text: t.content,
      }));
      setMessages((prev) => {
        const hydratedIds = new Set(hydrated.map((m) => m.id));
        const head: ChatMessage[] = [];
        // Locally-added turns the replay doesn't cover yet — above all the
        // campaign kickoff greeting (with its reading-list chips) streaming in on
        // THIS mount, since autoKickoff and hydrate fire together when the
        // dashboard resumes the intake session. listTurns resolves before the LLM
        // finishes, so a plain `[head, ...hydrated]` replace would silently drop
        // that streaming bubble. Keep such turns and re-append them AFTER the
        // replayed history so the greeting survives (and reads chronologically).
        const localLive: ChatMessage[] = [];
        for (const m of prev) {
          if (m.role === "system" && m.id.endsWith("-sys")) head.push(m);
          else if (!hydratedIds.has(m.id) && m.id.startsWith(`${audience}-`)) localLive.push(m);
        }
        return [...head, ...hydrated, ...localLive];
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrateHistory, canChat, ensureSession, apiBaseUrl, accessToken, audience]);

  useEffect(() => {
    const ref = abortRef;
    const timers = revealTimersRef;
    return () => {
      ref.current?.abort();
      // Cancel any pending staggered reveals so they don't fire post-unmount.
      for (const t of timers.current) clearTimeout(t);
      timers.current = [];
    };
  }, []);

  const handleSubmit = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !canChat) return;
      // Ambient card context: the agent silently learns which card is on screen
      // (the Journal's scroll/click-focused card) instead of us mangling the
      // message text. The turn text itself is exactly what the user typed — the
      // focused card rides along as a hidden `viewing_node_id`, resolved to a
      // card server-side.
      const viewingNodeId = storeApi.getState().focusedNodeId;
      const n = (seqRef.current += 1);
      const userId = `${audience}-u-${n}`;
      const assistantId = `${audience}-a-${n}`;
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", text: trimmed },
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
        await sendTurn(
          trimmed,
          viewingNodeId ? { viewing_node_id: viewingNodeId } : undefined,
        );
      })();
    },
    [audience, canChat, ensureSession, appendDelta, sendTurn, storeApi],
  );

  // Accept a proposed card. This just moves the (already-`pending`) node from
  // the proposal tray onto the plan — it is NOT an approval/lock (the store
  // keeps it `pending`), and it's no chat turn, so the agent is not confused
  // by a second pending card still on screen. Three things happen without a
  // reload: the card lands on the plan (optimistic — it survives the
  // refresh below), it's SELECTED (the rail/ambient layer follow
  // `focusedNodeId`) and REVEALED on the spine. The day scaffold is
  // server-rendered (see TimelineDataContext), so the node's own date may not
  // have a day section until the RSC re-runs — hence the `router.refresh()` + a
  // retrying scroll that waits for the card to mount.
  const acceptProposal = useCallback(
    (id: string) => {
      const st = storeApi.getState();
      st.acceptProposal(id);
      st.focusNode(id, "click");
      router.refresh();
      scrollNodeIntoView(id, revealTimersRef);
    },
    [storeApi, router],
  );

  // Dismiss a proposal: soft-remove the card (the store persists it as
  // `discarded`) and refresh the server-rendered timeline so it drops off.
  const dismissProposal = useCallback(
    (id: string) => {
      storeApi.getState().dismissProposal(id);
      router.refresh();
    },
    [storeApi, router],
  );

  // Campaign dashboard kickoff (fires at most once). Two phases:
  //   1. DETERMINISTIC spine — POST /campaign/kickoff lays the curated skeleton
  //      (+ its outdoorvoyage.com cornerstone) onto the traveler's itinerary and
  //      returns the created nodes. We drop them into the store staggered, the
  //      same "cards appearing" reveal a streamed spine used to get — but now it
  //      happens instantly and reliably, not gated on the model choosing to call
  //      a tool. Idempotent: a re-fire on a populated trip is a server no-op.
  //   2. AGENT OPENER — one `surface: "kickoff"` turn. The spine is already on
  //      screen, so the agent's job is just to greet it and ask about the gaps
  //      (dates / party / the way in). NO visible user bubble — the trigger text
  //      is stored server-side but reads naturally if ever replayed.
  const kickedOff = useRef(false);
  useEffect(() => {
    if (!autoKickoff || kickedOff.current || !canChat) return;
    if (!apiBaseUrl || !accessToken) return;
    kickedOff.current = true;
    const assistantId = `${audience}-a-${(seqRef.current += 1)}`;
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", text: "", streaming: true },
    ]);
    streamingIdRef.current = assistantId;
    setStreaming(true);
    setWorking(true);
    void (async () => {
      // Phase 1: lay the spine deterministically and reveal it staggered.
      const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const laid = await campaignKickoff(api, itineraryId);
      let revealBurst = 0;
      if (laid.ok) {
        const created = laid.kickoff.created_nodes ?? [];
        revealBurst = created.length;
        created.forEach((node, i) => {
          const timer = setTimeout(() => {
            storeApi.getState().insertCreatedNode({
              id: node.id,
              itinerary_id: node.itinerary_id,
              // Cornerstone day-children carry a parent — keep it so they derive
              // as journey beats live, not as parentless top-level cards.
              parent_subgraph_id: node.parent_subgraph_id ?? null,
              type: node.type,
              status: node.status,
              title: node.title,
              source: node.source ?? null,
              source_id: node.source_id ?? null,
              metadata: node.metadata ?? {},
            });
          }, i * REVEAL_STAGGER_MS);
          revealTimersRef.current.push(timer);
        });
      }
      // The spine set the trip's dates; the day scaffold is server-rendered, so
      // rebuild it once the reveal burst has settled (mirrors the onDone path).
      if (revealBurst > 0) {
        const timer = setTimeout(
          () => router.refresh(),
          revealBurst * REVEAL_STAGGER_MS + REVEAL_STAGGER_MS,
        );
        revealTimersRef.current.push(timer);
      }

      // Phase 2: the agent greets what's on screen and asks about the gaps.
      const sid = await ensureSession();
      if (!sid) {
        setWorking(false);
        streamingIdRef.current = null;
        setStreaming(false);
        return;
      }
      await sendTurn("Let's build it out.", { surface: "kickoff" });
    })();
  }, [
    autoKickoff,
    canChat,
    audience,
    apiBaseUrl,
    accessToken,
    itineraryId,
    storeApi,
    router,
    ensureSession,
    sendTurn,
  ]);

  // Resolve an `article:<nodeId>` chip (from the concierge's kickoff greeting)
  // to the read it stands for — read live from the graph store, where the
  // deterministic kickoff dropped the reading-list nodes. Null for a stale/
  // unknown id, which makes ArticleChip fall back to a plain label.
  const resolveArticle = useCallback(
    (nodeId: string): ArticleSurfaceView | null =>
      articleViewFromNode(storeApi.getState().nodes.find((n) => n.id === nodeId)),
    [storeApi],
  );

  // A tapped option answers through the ordinary turn path, phrased as the
  // traveler's own reply — the agent reads it like any message.
  const onChooseOption = useCallback(
    (option: OptionView) => {
      close();
      handleSubmit(optionReply(option));
    },
    [close, handleSubmit],
  );

  return (
    <div ref={panelRef} className="flex h-full min-h-0 flex-col">
      <SurfaceContext.Provider value={opener}>
        <ArticleResolverContext.Provider value={resolveArticle}>
          <ConversationPanel
            messages={messages}
            proposals={pendingProposals}
            onAccept={acceptProposal}
            onDismiss={dismissProposal}
            onSubmit={handleSubmit}
            {...(onScrollToNode ? { onScrollToNode } : {})}
            disabled={!canChat}
            sending={streaming}
            hideHeader={hideHeader}
            working={working}
          />
        </ArticleResolverContext.Provider>
      </SurfaceContext.Provider>
      <AgentSurface
        surface={surface}
        busy={!canChat || streaming}
        onClose={close}
        onChooseOption={onChooseOption}
        anchorRef={panelRef}
        side={surfaceSide}
      />
    </div>
  );
}
