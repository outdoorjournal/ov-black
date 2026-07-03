"use client";

// The persistent right-rail chat surface for /basecamp variants (c) and (d).
//
// Reuses the existing onboarding session via createSessionEndpoint
// (idempotent) — no new DB session is created on every visit. Prior turns
// are loaded server-side and seeded into the store so the rail is never
// empty: the user sees their conversation history with one composer
// underneath, ready to continue.
//
// AtmosFrame still runs here so the agent's set_mood calls keep updating
// the ambience. The mood applies only to the rail itself (which sits in
// its own positioned container) — the basecamp chrome stays intact.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  createApiClient,
  createSessionEndpoint,
  type AgentTurnSummary,
} from "@ov-black/api-client";

import { Eyebrow } from "@/components/ui/eyebrow";
import { AtmosFrame } from "@/app/chat/[client_id]/_components/AtmosFrame";
import { ConversationStream } from "@/app/chat/[client_id]/_components/ConversationStream";
import { Composer } from "@/app/chat/[client_id]/_components/Composer";
import {
  useAgentStream,
  type DeltaFrame,
  type DoneFrame,
  type ErrorFrame,
  type MoodFrame,
} from "@/lib/agentStream";
import { DEFAULT_MOOD, type MoodId } from "@/lib/atmos/moods";
import { createBrowserSupabase } from "@/lib/supabase/client";

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
}: RightRailChatProps) {
  const turns = basecampChatStore.useStore((s) => s.turns);
  const streaming = basecampChatStore.useStore((s) => s.streaming);
  const currentMood = basecampChatStore.useStore((s) => s.currentMood);
  const storeApi = basecampChatStore.useStoreApi();

  const router = useRouter();
  const sessionIdRef = useRef<string | null>(existingSessionId);
  const abortRef = useRef<AbortController | null>(null);
  const moodPhaseRef = useRef(0);
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

  const { sendTurn } = useAgentStream({
    sessionId: sessionIdRef.current ?? "",
    getAccessToken,
    apiBaseUrl,
    abortRef,
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
        moodPhaseRef.current += 1;
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

  useEffect(() => {
    const ref = abortRef;
    return () => {
      ref.current?.abort();
    };
  }, []);

  return (
    <aside className="relative flex h-[calc(100vh-7rem)] flex-col overflow-hidden rounded-sm bg-paper text-ink shadow-float lg:sticky lg:top-24">
      <AtmosFrame mood={currentMood ?? DEFAULT_MOOD} phaseCounter={moodPhaseRef.current} />
      <div className="relative z-10 flex min-h-0 flex-1 flex-col bg-paper/95 backdrop-blur-sm">
        <header className="border-b border-ink/10 px-6 pb-4 pt-5">
          <Eyebrow>Concierge</Eyebrow>
          <h2 className="mt-2 font-serif text-xl text-ink">
            {turns.length > 0 ? "Continue your conversation" : "Reach the concierge"}
          </h2>
        </header>
        <div className="min-h-0 flex-1 [&>section]:h-full">
          <ConversationStream turns={turns} streaming={streaming} />
        </div>
        <Composer disabled={streaming !== null} onSend={onSend} />
      </div>
    </aside>
  );
}
