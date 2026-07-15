"use client";

// The persistent concierge column for /basecamp variants (c) and (d).
//
// Reuses the existing onboarding session via createSessionEndpoint
// (idempotent) — no new DB session is created on every visit. Prior turns
// are loaded server-side and seeded into the store so the rail is never
// empty: the user sees their conversation history with one composer
// underneath, ready to continue.
//
// M006/PS7: this now renders as a FLAT paper column — the same chrome as the
// itinerary ConciergeColumn (people-circles top nav + Artemis stream / Advisor
// human channel), no frosted floating card and no AtmosFrame mood tint — so the
// two surfaces' chat windows look and sit the same. The host (ConciergeSplit)
// supplies the bounded height + border; the first-touch immersive mood lives in
// SinglePromptCard, not here. `set_mood` is still tracked in the store (unused
// visually) so the agent path is unchanged.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  addToReadingList,
  createApiClient,
  createSessionEndpoint,
  type AgentTurnSummary,
} from "@ov-black/api-client";

import {
  ConversationPanel,
  type ConversationMessage,
} from "@/app/_components/concierge/ConversationPanel";
import { AgentSurface } from "@/app/_components/concierge/surfaces/AgentSurface";
import { SurfaceContext } from "@/app/_components/concierge/surfaces/SurfaceContext";
import type {
  ArticleSurfaceView,
  OptionView,
} from "@/app/_components/concierge/surfaces/types";
import {
  optionReply,
  useAgentSurface,
} from "@/app/_components/concierge/surfaces/useAgentSurface";
import {
  useAgentStream,
  type DeltaFrame,
  type DoneFrame,
  type ErrorFrame,
  type MoodFrame,
} from "@/lib/agentStream";
import { type MoodId } from "@/lib/atmos/moods";
import { createBrowserSupabase } from "@/lib/supabase/client";
import { HumanThread } from "@/app/itinerary/[id]/_shell/HumanThread";
import {
  PeopleCircles,
  type ConciergeChannel,
} from "@/app/_components/concierge/PeopleCircles";

import { basecampChatStore, nextTurnIndex } from "./basecampChatStore";

const MOOD_ID_VALUES: ReadonlySet<string> = new Set([
  "glacial",
  "ember",
  "amber",
  "verdant",
  "tidal",
  "onyx",
  "alpine",
  "paris-cafe",
  "kyoto-zen",
  "savannah",
  "polar",
  "andes",
  "monsoon",
  "riviera",
  "highland",
]);

function asMoodId(value: string): MoodId | null {
  return MOOD_ID_VALUES.has(value) ? (value as MoodId) : null;
}

// The concierge's opening line on a fresh basecamp — shown as a leading
// assistant bubble whenever the traveler lands on the null-itinerary chat with
// no prior turns, so the rail is never a blank void. Display-only (not persisted
// as a turn): it stays pinned above whatever the traveler types this session,
// and a returning traveler with real history opens on that history instead.
// "Artemis" is the name the traveler already sees on this channel (PeopleCircles).
const BASECAMP_GREETING =
  "Hello — I'm Artemis, your concierge. Tell me about a place you've been " +
  "dreaming of, or ask me anything at all. We'll begin wherever you like.";

export type RightRailChatProps = {
  clientId: string;
  accessToken: string;
  apiBaseUrl: string;
  initialTurns: AgentTurnSummary[];
  // Pre-resolved by the page when an onboarding session already exists.
  // Null indicates we need to lazily open one on first send (rare in
  // practice — variant (c)/(d) is reached only with prior turns).
  existingSessionId: string | null;
  // The server's onboarding_complete verdict at last render. We watch it for a
  // false→true flip (after a post-turn refresh) to fire the milestone card.
  onboardingComplete: boolean;
  // Collapse the ≥lg in-flow column to the edge tab (mirrors the itinerary
  // ConciergeColumn's Q5 collapse). Absent below lg, where the chat is a
  // bounded block rather than a sidebar.
  onCollapse?: () => void;
};

export function RightRailChat(props: RightRailChatProps) {
  return (
    <basecampChatStore.Provider initial={{ initialTurns: props.initialTurns }}>
      <RightRailChatInner {...props} />
    </basecampChatStore.Provider>
  );
}

function RightRailChatInner({
  clientId,
  accessToken,
  apiBaseUrl,
  existingSessionId,
  onboardingComplete,
  onCollapse,
}: RightRailChatProps) {
  const turns = basecampChatStore.useStore((s) => s.turns);
  const streaming = basecampChatStore.useStore((s) => s.streaming);
  // How many turns loaded from the server at mount. Zero → a fresh basecamp with
  // no history, so Artemis leads with a greeting (below).
  const initialTurnsCount = basecampChatStore.useStore(
    (s) => s.initialTurnsCount,
  );
  const storeApi = basecampChatStore.useStoreApi();

  // PS7 unify: the basecamp rail carries both channels — Artemis (this AI
  // onboarding stream) and Advisor (the human "you ↔ advisor" thread, basecamp
  // scope = itinerary_id NULL). The agent stream hook stays mounted below
  // regardless, so switching to Advisor never interrupts an in-flight turn.
  const [channel, setChannel] = useState<ConciergeChannel>("artemis");

  const router = useRouter();
  const sessionIdRef = useRef<string | null>(existingSessionId);
  const abortRef = useRef<AbortController | null>(null);
  // The rail sits on the LEFT of the screen (ConciergeSplit's aside is
  // lg:order-1) — the same placement as the itinerary shell's ConciergeColumn —
  // so the drawer flyout anchors here and slides out to the RIGHT, over the
  // basecamp content beside it.
  const railRef = useRef<HTMLDivElement | null>(null);
  // Prior onboarding_complete value, for false→true flip detection.
  const prevOnboardingCompleteRef = useRef(onboardingComplete);

  // Fire the milestone card once, the moment the server's verdict flips true
  // (after a post-turn refresh re-reads it). commitMilestone is itself
  // fire-once, so this is belt-and-braces.
  useEffect(() => {
    if (!prevOnboardingCompleteRef.current && onboardingComplete) {
      storeApi.getState().commitMilestone();
    }
    prevOnboardingCompleteRef.current = onboardingComplete;
  }, [onboardingComplete, storeApi]);

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

  // The drawer beside the conversation — agent-pushed panels (route brochure,
  // decision cards) and chip-opened place briefs share one host.
  const { surface, onSurface, opener, close } = useAgentSurface();

  const { sendTurn } = useAgentStream({
    sessionId: sessionIdRef.current ?? "",
    getAccessToken,
    apiBaseUrl,
    abortRef,
    onSurface,
    onDelta: (frame: DeltaFrame) => {
      storeApi.getState().appendDelta(frame.text);
    },
    onDone: (frame: DoneFrame) => {
      storeApi.getState().finishStream(frame);
      // Still onboarding? Re-read the server's verdict. A fact the agent
      // recorded this turn may have satisfied the rule — the refresh both
      // clears the reminder (server re-renders) and flips onboardingComplete,
      // which the effect above turns into the milestone card. Soft refresh:
      // the chat store and this component keep their state.
      if (!onboardingComplete) {
        router.refresh();
      }
    },
    onError: (frame: ErrorFrame) => {
      storeApi.getState().errorStream(frame);
    },
    onItineraryUpdated: () => {
      // Agent set the trip's dates. Basecamp renders trip timing server-side
      // (the itinerary cards), so re-pull it; the chat store keeps its state.
      router.refresh();
    },
    onMood: (frame: MoodFrame) => {
      const mood = asMoodId(frame.mood_id);
      if (mood) {
        storeApi.getState().setMood(mood);
      }
    },
  });

  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    const token = await getAccessToken();
    if (!token) return null;
    const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
    const result = await createSessionEndpoint(api, { client_id: clientId });
    if (!result.ok) return null;
    sessionIdRef.current = result.session_id;
    return result.session_id;
  }, [apiBaseUrl, clientId, getAccessToken]);

  const onSend = useCallback(
    (content: string) => {
      void (async () => {
        const sid = await ensureSession();
        if (!sid) {
          storeApi.getState().errorStream({ type: "error", reason: "upstream_unavailable" });
          return;
        }
        const state = storeApi.getState();
        const idx = nextTurnIndex(state.turns);
        state.commitUserTurn({
          id: `user-${idx}-${Date.now()}`,
          turn_index: idx,
          role: "user",
          content,
        });
        state.startStream(idx + 1);
        void sendTurn(content);
      })();
    },
    [ensureSession, sendTurn, storeApi],
  );

  // A tapped option answers through the ordinary turn path, phrased as the
  // traveler's own reply — the agent reads it like any message.
  const onChooseOption = useCallback(
    (option: OptionView) => {
      close();
      onSend(optionReply(option));
    },
    [close, onSend],
  );

  // "Add to reading list" on an article flyout writes straight to the
  // Collection (no turn) — the metadata is already in hand, so no OG re-fetch.
  // The panel stays open and swaps its button to "Added"; returning ok drives
  // that. Uses a live token (getAccessToken) so a long basecamp sit can't 401.
  const onAddToReadingList = useCallback(
    async (article: ArticleSurfaceView): Promise<boolean> => {
      const token = await getAccessToken();
      if (!token) return false;
      const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
      const result = await addToReadingList(api, {
        title: article.title,
        url: article.url,
        publication: article.publication ?? null,
        og_image: article.ogImage ?? null,
        excerpt: article.excerpt ?? null,
      });
      return result.ok;
    },
    [apiBaseUrl, getAccessToken],
  );

  useEffect(() => {
    const ref = abortRef;
    return () => {
      ref.current?.abort();
    };
  }, []);

  // Normalise the basecamp turn model onto the shared ConversationPanel shape.
  // AgentTurnView.role is a superset of ConversationRole (they share
  // user/assistant/system/tool/error/milestone), so roles pass straight
  // through; the in-flight buffer becomes a trailing streaming bubble.
  const messages: ConversationMessage[] = [];
  // No history → open with Artemis' greeting, pinned above anything the traveler
  // sends this session (gated on the server's mount-time count, not live turns,
  // so it doesn't vanish the moment they reply).
  if (initialTurnsCount === 0) {
    messages.push({
      id: "basecamp-greeting",
      role: "assistant",
      text: BASECAMP_GREETING,
    });
  }
  messages.push(
    ...turns.map((t) => ({
      id: t.id,
      role: t.role,
      text: t.content,
    })),
  );
  if (streaming) {
    messages.push({
      id: `streaming-${streaming.turnIndex}`,
      role: "assistant",
      text: streaming.buffer,
      streaming: true,
    });
  }

  // Flat paper column — the SAME chrome as the itinerary ConciergeColumn (no
  // frosted/floating card, no AtmosFrame). The host (BasecampShell) provides the
  // bounded height + border, so this just fills it, exactly like the itinerary
  // concierge fills its aside. The Artemis body now renders the SHARED
  // ConversationPanel (bubbles) — the same window the advisor sees, not the
  // /chat prose stream — so both surfaces read identically.
  return (
    <div
      ref={railRef}
      data-testid="basecamp-concierge"
      className="flex h-full min-h-0 flex-col bg-paper text-ink"
    >
      {/* Same top nav as the itinerary concierge — the people-circles channel
          switch (Artemis ↔ Advisor). The basecamp Advisor thread is basecamp-
          scoped (you ↔ advisor, itinerary_id NULL) — a separate conversation
          from any trip's thread. */}
      <PeopleCircles
        channel={channel}
        onSelect={setChannel}
        advisorTitle="Message your advisor"
        trailing={
          onCollapse ? (
            <button
              type="button"
              onClick={onCollapse}
              data-testid="basecamp-concierge-collapse"
              aria-label="Collapse the concierge"
              className="ml-auto hidden h-7 items-center rounded-md px-2 font-sans text-base text-ink/45 transition-colors hover:bg-ink/5 hover:text-ink lg:flex"
            >
              ‹
            </button>
          ) : null
        }
      />
      {/* Both channels share the space below the top nav. The Artemis stream
          body stays mounted (the useAgentStream hook lives at the top of this
          component, so a hidden body never drops an in-flight turn); the
          streamless human body mounts on demand. */}
      <div className="relative min-h-0 flex-1">
        <div
          className={
            channel === "artemis" ? "absolute inset-0 flex flex-col" : "hidden"
          }
        >
          <SurfaceContext.Provider value={opener}>
            <ConversationPanel
              messages={messages}
              onSubmit={onSend}
              sending={streaming !== null}
              hideHeader
              placeholder="Write to your concierge"
            />
          </SurfaceContext.Provider>
        </div>
        {channel === "human" ? (
          <div className="absolute inset-0 flex flex-col">
            <HumanThread
              clientId={clientId}
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              viewerKind="traveler"
            />
          </div>
        ) : null}
      </div>
      <AgentSurface
        surface={surface}
        busy={streaming !== null}
        onClose={close}
        onChooseOption={onChooseOption}
        onAddToReadingList={onAddToReadingList}
        anchorRef={railRef}
        side="right"
      />
    </div>
  );
}
