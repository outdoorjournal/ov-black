"use client";

// Variant (a) → (b) for /basecamp.
//
// The first-time experience: one Cormorant heading carrying the picked
// opener, one Textarea below, one "Reply" button. When the user submits,
// the same component flips `engaged: true` and renders the conversation
// view in place — opener fades up + shrinks, conversation fades in below,
// AtmosFrame appears and crossfades as the agent calls set_mood.
//
// Lazy session creation: we deliberately do NOT call createSessionEndpoint
// on mount. A new client landing here who immediately bounces shouldn't
// leave an orphan agent_session row. The session is opened on the first
// submit, with seeded_opener attached so the agent's directive lands on
// turn 0 and its first streamed line is the opener verbatim.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  createApiClient,
  createSessionEndpoint,
  dismissOnboarding,
  getMyOnboardingSession,
  type OnboardingOpenerResponse,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
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
import { AgentSurface } from "@/app/_components/concierge/surfaces/AgentSurface";
import { SurfaceContext } from "@/app/_components/concierge/surfaces/SurfaceContext";
import type { OptionView } from "@/app/_components/concierge/surfaces/types";
import {
  optionReply,
  useAgentSurface,
} from "@/app/_components/concierge/surfaces/useAgentSurface";

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

export type SinglePromptCardProps = {
  opener: OnboardingOpenerResponse;
  clientId: string;
  accessToken: string;
  apiBaseUrl: string;
};

export function SinglePromptCard({
  opener,
  clientId,
  accessToken,
  apiBaseUrl,
}: SinglePromptCardProps) {
  return (
    <basecampChatStore.Provider initial={{ initialTurns: [] }}>
      <SinglePromptInner
        opener={opener}
        clientId={clientId}
        accessToken={accessToken}
        apiBaseUrl={apiBaseUrl}
      />
    </basecampChatStore.Provider>
  );
}

function SinglePromptInner({
  opener,
  clientId,
  accessToken,
  apiBaseUrl,
}: SinglePromptCardProps) {
  const turns = basecampChatStore.useStore((s) => s.turns);
  const streaming = basecampChatStore.useStore((s) => s.streaming);
  const currentMood = basecampChatStore.useStore((s) => s.currentMood);
  const storeApi = basecampChatStore.useStoreApi();

  const router = useRouter();

  const [engaged, setEngaged] = useState(false);
  const [draft, setDraft] = useState("");
  const [openingError, setOpeningError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The drawer flyout anchors to the engaged conversation card and slides
  // out to its right, over the Atmos backdrop.
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const moodPhaseRef = useRef(0);
  // Fire-once guard for the milestone card. The first-touch card can't
  // router.refresh() (it would flip the server variant and unmount this
  // conversation mid-stream), so after each turn we poll the onboarding verdict
  // directly and drop the card in place when it flips true.
  const milestoneFiredRef = useRef(false);

  // Token provider (mirrors ChatShell). Pulled fresh on every send so an
  // expired SSR token gets replaced by the auto-refreshed one in the
  // browser supabase client.
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

  // The drawer beside the conversation — agent-pushed panels and chip-opened
  // place briefs share one host (only visible in the engaged phase).
  const { surface, onSurface, opener: surfaceOpener, close } = useAgentSurface();

  // useAgentStream needs a sessionId. The session is opened lazily on
  // the very first submit, so we point the hook at a getter backed by
  // sessionIdRef — that ref is written synchronously inside submit
  // before sendTurn fires, while a useState binding would still be
  // empty on the same tick (React hasn't re-rendered yet).
  const { sendTurn } = useAgentStream({
    getSessionId: () => sessionIdRef.current,
    getAccessToken,
    apiBaseUrl,
    abortRef,
    onSurface,
    onDelta: (frame: DeltaFrame) => {
      storeApi.getState().appendDelta(frame.text);
    },
    onDone: (frame: DoneFrame) => {
      storeApi.getState().finishStream(frame);
      // After the turn settles, poll the server's onboarding verdict. If a fact
      // the agent just recorded satisfied the rule, drop the milestone card in
      // place. No router.refresh() here (it would unmount this first-touch view).
      if (!milestoneFiredRef.current) {
        void (async () => {
          const token = await getAccessToken();
          if (!token) return;
          const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
          const result = await getMyOnboardingSession(api);
          if (result.ok && result.session.onboarding_complete) {
            milestoneFiredRef.current = true;
            storeApi.getState().commitMilestone();
          }
        })();
      }
    },
    onError: (frame: ErrorFrame) => {
      storeApi.getState().errorStream(frame);
    },
    onMood: (frame: MoodFrame) => {
      const mood = asMoodId(frame.mood_id);
      if (mood) {
        moodPhaseRef.current += 1;
        storeApi.getState().setMood(mood);
      }
    },
  });

  const submit = useCallback(async () => {
    const trimmed = draft.trim();
    if (trimmed.length === 0 || opening || streaming !== null) return;

    if (sessionIdRef.current === null) {
      setOpening(true);
      const token = await getAccessToken();
      if (!token) {
        setOpeningError("upstream_unavailable");
        setOpening(false);
        return;
      }
      const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
      const result = await createSessionEndpoint(api, {
        client_id: clientId,
        seeded_opener: opener.prompt,
      });
      if (!result.ok) {
        setOpeningError(result.detail);
        setOpening(false);
        return;
      }
      sessionIdRef.current = result.session_id;
      setOpening(false);
    }

    // Seed the conversation view with the opener as turn-0 assistant. The
    // agent's directive instructs it to echo this verbatim as its first
    // streamed line — the seed gives the morph something to anchor on
    // until the real assistant turn arrives.
    storeApi.getState().commitAssistantSeed(opener.prompt);

    // Optimistic user-turn row.
    const state = storeApi.getState();
    const optimisticIndex = nextTurnIndex(state.turns);
    state.commitUserTurn({
      id: `user-${optimisticIndex}-${Date.now()}`,
      turn_index: optimisticIndex,
      role: "user",
      content: trimmed,
    });
    storeApi.getState().startStream(optimisticIndex + 1);
    setDraft("");
    setEngaged(true);
    void sendTurn(trimmed);
  }, [
    apiBaseUrl,
    clientId,
    draft,
    getAccessToken,
    opener.prompt,
    opening,
    sendTurn,
    storeApi,
    streaming,
  ]);

  // Follow-up sends in the engaged phase — shared by the Composer and the
  // options-surface pick (which answers as the traveler's own reply).
  const sendFollowUp = useCallback(
    (content: string) => {
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
    },
    [sendTurn, storeApi],
  );

  const onChooseOption = useCallback(
    (option: OptionView) => {
      close();
      sendFollowUp(optionReply(option));
    },
    [close, sendFollowUp],
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void submit();
      }
    },
    [submit],
  );

  // Skip (variant a) / Close (variant b): cancel any in-flight stream,
  // call POST /onboarding/dismiss, then refresh the route. The server
  // re-renders with `has_prior_session=true`, swapping basecamp into
  // post_first_touch which mounts RightRailChat and unmounts this card.
  const dismiss = useCallback(async () => {
    if (dismissing) return;
    setDismissing(true);
    abortRef.current?.abort();
    const token = await getAccessToken();
    if (!token) {
      setDismissing(false);
      setOpeningError("upstream_unavailable");
      return;
    }
    const api = createApiClient({ baseUrl: apiBaseUrl, accessToken: token });
    const result = await dismissOnboarding(api);
    if (!result.ok) {
      setDismissing(false);
      setOpeningError(result.detail);
      return;
    }
    router.refresh();
  }, [apiBaseUrl, dismissing, getAccessToken, router]);

  // Cancel any in-flight stream on unmount.
  useEffect(() => {
    const ref = abortRef;
    return () => {
      ref.current?.abort();
    };
  }, []);

  return (
    <div className="relative" data-engaged={engaged}>
      {engaged ? (
        <AtmosFrame mood={currentMood ?? DEFAULT_MOOD} phaseCounter={moodPhaseRef.current} />
      ) : null}

      <div
        className={
          engaged
            ? "relative z-10 mx-auto flex h-[calc(100vh-5.5rem)] max-w-3xl flex-col gap-8 px-6 pb-12 pt-6 sm:px-10"
            : "relative z-10 mx-auto flex min-h-[calc(100vh-5.5rem)] max-w-3xl flex-col items-center justify-center gap-12 px-6 pb-16 sm:px-10"
        }
        data-phase={engaged ? "conversation" : "prompt"}
      >
        <h1
          key="opener"
          className={
            engaged
              ? "font-serif text-2xl leading-snug tracking-tight text-paper transition-all duration-700 ease-out sm:text-3xl"
              : "max-w-3xl text-balance text-center font-serif text-4xl leading-[1.15] tracking-tight text-ink transition-all duration-700 ease-out sm:text-5xl lg:text-6xl"
          }
        >
          {opener.prompt}
        </h1>

        {!engaged ? (
          <div className="flex w-full max-w-2xl flex-col items-center gap-4">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Begin in your own words…"
              rows={3}
              className="w-full resize-none rounded-sm border border-ink/15 bg-white px-5 py-4 font-sans text-base leading-relaxed text-ink transition placeholder:text-ink/40 focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/25"
              autoFocus
              disabled={opening}
            />
            <div className="flex items-center gap-4">
              <Button
                type="button"
                variant="brand"
                onClick={() => void submit()}
                disabled={opening || draft.trim().length === 0}
                className="uppercase tracking-label"
              >
                {opening ? "Connecting…" : "Reply"}
              </Button>
              <span className="text-[10px] uppercase tracking-eyebrow text-ink/45">
                Press Enter to begin
              </span>
              <button
                type="button"
                onClick={() => void dismiss()}
                disabled={dismissing || opening}
                className="text-[10px] uppercase tracking-eyebrow text-ink/45 transition hover:text-ink/80 disabled:opacity-40"
              >
                {dismissing ? "Closing…" : "Not now"}
              </button>
            </div>
            {openingError ? (
              <p className="text-sm text-ink/60">
                Our concierge is stepping away for a moment. Please try again.
              </p>
            ) : null}
          </div>
        ) : (
          <div
            ref={conversationRef}
            className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-hidden rounded-sm bg-paper text-ink shadow-float"
          >
            <button
              type="button"
              onClick={() => void dismiss()}
              disabled={dismissing}
              aria-label="Close conversation"
              className="absolute right-4 top-4 z-10 rounded-sm px-2 py-1 font-sans text-[10px] uppercase tracking-eyebrow text-ink/45 transition hover:text-ink/80 disabled:opacity-40"
            >
              {dismissing ? "Closing…" : "Close"}
            </button>
            <div className="min-h-0 flex-1 [&>section]:h-full">
              <SurfaceContext.Provider value={surfaceOpener}>
                <ConversationStream turns={turns} streaming={streaming} />
              </SurfaceContext.Provider>
            </div>
            <Composer
              disabled={streaming !== null}
              onSend={sendFollowUp}
            />
            <AgentSurface
              surface={surface}
              busy={streaming !== null}
              onClose={close}
              onChooseOption={onChooseOption}
              anchorRef={conversationRef}
              side="right"
            />
          </div>
        )}
      </div>
    </div>
  );
}
