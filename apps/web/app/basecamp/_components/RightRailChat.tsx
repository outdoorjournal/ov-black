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
  createApiClient,
  createSessionEndpoint,
  type AgentTurnSummary,
} from "@ov-black/api-client";

import { ConversationStream } from "@/app/chat/[client_id]/_components/ConversationStream";
import { Composer } from "@/app/chat/[client_id]/_components/Composer";
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
  const storeApi = basecampChatStore.useStoreApi();

  // PS7 unify: the basecamp rail carries both channels — Artemis (this AI
  // onboarding stream) and Advisor (the human "you ↔ advisor" thread, basecamp
  // scope = itinerary_id NULL). The agent stream hook stays mounted below
  // regardless, so switching to Advisor never interrupts an in-flight turn.
  const [channel, setChannel] = useState<ConciergeChannel>("artemis");

  const router = useRouter();
  const sessionIdRef = useRef<string | null>(existingSessionId);
  const abortRef = useRef<AbortController | null>(null);
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

  // Flat paper column — the SAME chrome as the itinerary ConciergeColumn (no
  // frosted/floating card, no AtmosFrame). The host (BasecampShell) provides the
  // bounded height + border, so this just fills it, exactly like the itinerary
  // concierge fills its aside.
  return (
    <div
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
          <div className="min-h-0 flex-1 [&>section]:h-full">
            <ConversationStream turns={turns} streaming={streaming} />
          </div>
          <Composer disabled={streaming !== null} onSend={onSend} />
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
    </div>
  );
}
