"use client";

// Variant (a) → (b) for /basecamp — the first-touch onboarding, restyled to
// match the immersive intake screen (app/itinerary/[id]/new): a cinematic,
// mood-aware backdrop, one floating paper chat card, and a quiet ledger beside
// it that lights a checkmark as the agent captures onboarding's two goals —
// the traveler's dream destination and one real thing about them. Both land as
// profile facts; the agent surfaces each to this card with a `profile_updated`
// SSE frame (kind only), and the ledger keys the right checkmark off the kind.
//
// Lazy session creation is preserved: we deliberately do NOT call
// createSessionEndpoint on mount, so a new client who immediately bounces
// leaves no orphan agent_session row. The session opens on the first reply,
// with seeded_opener attached so the agent's directive lands on turn 0 and its
// first streamed line is the opener verbatim.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createApiClient,
  createSessionEndpoint,
  dismissOnboarding,
  getMyOnboardingSession,
  type OnboardingOpenerResponse,
} from "@ov-black/api-client";

import { CinematicBackdrop } from "@/app/_components/atmos/CinematicBackdrop";
import {
  ConversationPanel,
  type ConversationMessage,
} from "@/app/_components/concierge/ConversationPanel";
import {
  useAgentStream,
  type DeltaFrame,
  type DoneFrame,
  type ErrorFrame,
  type MoodFrame,
  type ProfileUpdatedFrame,
} from "@/lib/agentStream";
import { type MoodId } from "@/lib/atmos/moods";
import { createBrowserSupabase } from "@/lib/supabase/client";
import { AgentSurface } from "@/app/_components/concierge/surfaces/AgentSurface";
import { SurfaceContext } from "@/app/_components/concierge/surfaces/SurfaceContext";
import type { OptionView } from "@/app/_components/concierge/surfaces/types";
import {
  optionReply,
  useAgentSurface,
} from "@/app/_components/concierge/surfaces/useAgentSurface";

import { basecampChatStore, nextTurnIndex } from "./basecampChatStore";
import { DESTINATION_FACT_KINDS, OnboardingLedger } from "./OnboardingLedger";

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
  // Display name for the greeting; null → plain "Welcome".
  clientName: string | null;
  accessToken: string;
  apiBaseUrl: string;
};

export function SinglePromptCard({
  opener,
  clientId,
  clientName,
  accessToken,
  apiBaseUrl,
}: SinglePromptCardProps) {
  return (
    <basecampChatStore.Provider initial={{ initialTurns: [] }}>
      <SinglePromptInner
        opener={opener}
        clientId={clientId}
        clientName={clientName}
        accessToken={accessToken}
        apiBaseUrl={apiBaseUrl}
      />
    </basecampChatStore.Provider>
  );
}

function SinglePromptInner({
  opener,
  clientId,
  clientName,
  accessToken,
  apiBaseUrl,
}: SinglePromptCardProps) {
  const turns = basecampChatStore.useStore((s) => s.turns);
  const streaming = basecampChatStore.useStore((s) => s.streaming);
  const storeApi = basecampChatStore.useStoreApi();

  const router = useRouter();

  const [engaged, setEngaged] = useState(false);
  const [openingError, setOpeningError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  // Local mood drives the cinematic backdrop: null → idle hero rotation, a
  // MoodId → the agent has committed to a place/vibe and we lock to it.
  const [mood, setMood] = useState<MoodId | null>(null);
  // Onboarding's two goals, each lit by a `profile_updated` frame: a
  // destination-kind fact (dream_signal / aspiration) and any other fact.
  const [destinationCaptured, setDestinationCaptured] = useState(false);
  const [factCaptured, setFactCaptured] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The drawer flyout slides out from the chat card's right edge, over the
  // backdrop; it spans the full-height column (headline included) via the
  // vertical anchor so it rises from the top of the room.
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const engagedColumnRef = useRef<HTMLDivElement | null>(null);
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
      const next = asMoodId(frame.mood_id);
      if (next) {
        setMood(next);
        storeApi.getState().setMood(next);
      }
    },
    onProfileUpdated: (frame: ProfileUpdatedFrame) => {
      // Kind only — the fact text never rides this frame. Route it to the goal
      // it satisfies: destination kinds light "dream destination", everything
      // else lights "something about you".
      if (DESTINATION_FACT_KINDS.has(frame.kind)) {
        setDestinationCaptured(true);
      } else {
        setFactCaptured(true);
      }
    },
  });

  // One send path for the whole screen. The first call lazily opens the
  // session (seeding the opener as turn-0 assistant so the morph has an
  // anchor); every call commits the optimistic user row and streams the turn.
  const handleSend = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
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
        setOpeningError(null);
        // Seed the opener as the turn-0 assistant line the first time through;
        // the agent echoes it verbatim, so the conversation opens coherently.
        storeApi.getState().commitAssistantSeed(opener.prompt);
        setEngaged(true);
      }

      const state = storeApi.getState();
      const idx = nextTurnIndex(state.turns);
      state.commitUserTurn({
        id: `user-${idx}-${Date.now()}`,
        turn_index: idx,
        role: "user",
        content: trimmed,
      });
      state.startStream(idx + 1);
      void sendTurn(trimmed);
    },
    [
      apiBaseUrl,
      clientId,
      getAccessToken,
      opener.prompt,
      opening,
      sendTurn,
      storeApi,
      streaming,
    ],
  );

  // A tapped option answers through the ordinary send path, phrased as the
  // traveler's own reply — same voice as the other chat shells.
  const onChooseOption = useCallback(
    (option: OptionView) => {
      close();
      void handleSend(optionReply(option));
    },
    [close, handleSend],
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

  const captured = destinationCaptured || factCaptured;

  // Normalise the basecamp turn model onto the shared ConversationPanel shape —
  // the SAME mapping RightRailChat uses, so the onboarding card, the returning
  // rail, and the trip intake all render through one chat component. Roles pass
  // straight through (AgentTurnView.role is a superset of ConversationRole); the
  // in-flight buffer becomes a trailing streaming bubble.
  const messages: ConversationMessage[] = turns.map((t) => ({
    id: t.id,
    role: t.role,
    text: t.content,
  }));
  if (streaming) {
    messages.push({
      id: `streaming-${streaming.turnIndex}`,
      role: "assistant",
      text: streaming.buffer,
      streaming: true,
    });
  }

  return (
    <div
      data-testid="onboarding-immersive"
      data-engaged={engaged}
      className="relative flex h-dvh flex-col overflow-hidden bg-ink text-paper"
    >
      <div className="absolute inset-0">
        <CinematicBackdrop mood={mood} />
      </div>

      {/* Minimal chrome: the wordmark. Below lg — where the ledger and its exit
          button are hidden — this quiet link keeps the way out reachable. */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <p className="font-sans text-[11px] uppercase tracking-[0.4em] text-paper/80">
          Outdoor Voyage
        </p>
        <button
          type="button"
          onClick={() => void dismiss()}
          disabled={dismissing}
          className="font-sans text-[11px] uppercase tracking-[0.22em] text-paper/60 transition hover:text-paper disabled:opacity-40 lg:hidden"
        >
          {dismissing ? "Closing…" : "Not now ›"}
        </button>
      </header>

      {/* The floating room: headline, chat card center, ledger beside it. */}
      <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center px-4 pb-6 sm:px-10">
        <div className="w-full max-w-5xl pb-6 pt-2 text-center lg:text-left">
          <p className="font-sans text-[11px] uppercase tracking-[0.3em] text-paper/55">
            {clientName ? `Welcome, ${clientName}` : "Welcome"}
          </p>
          <h1
            key="opener"
            className={
              engaged
                ? "mt-2 font-serif text-2xl leading-snug tracking-tight text-paper transition-all duration-700 ease-out sm:text-3xl"
                : "mt-2 font-serif text-4xl leading-tight tracking-tight text-paper transition-all duration-700 ease-out sm:text-5xl"
            }
          >
            {opener.prompt}
          </h1>
        </div>

        <div
          ref={engagedColumnRef}
          className="flex min-h-0 w-full max-w-5xl flex-1 items-stretch justify-center gap-8 lg:justify-start"
        >
          {/* The chat card — the SAME shared ConversationPanel the trip intake
              and the returning-visitor rail use, empty until the first reply
              opens the session, then the conversation grows in place. */}
          <div
            ref={conversationRef}
            data-testid="onboarding-chat"
            className="relative flex min-h-0 w-full max-w-xl flex-col overflow-hidden rounded-lg border border-paper/10 bg-paper text-ink shadow-2xl"
          >
            <SurfaceContext.Provider value={surfaceOpener}>
              <ConversationPanel
                messages={messages}
                onSubmit={(content) => void handleSend(content)}
                sending={streaming !== null || opening}
                hideHeader
                placeholder="Begin in your own words…"
              />
            </SurfaceContext.Provider>
            {openingError ? (
              <div className="absolute inset-x-0 top-0 z-30 bg-paper/95 px-4 py-2 text-center font-sans text-xs text-ink/60 shadow-sm backdrop-blur-sm">
                Our concierge is stepping away for a moment. Please try again.
              </div>
            ) : null}
            <AgentSurface
              surface={surface}
              busy={streaming !== null}
              onClose={close}
              onChooseOption={onChooseOption}
              anchorRef={conversationRef}
              verticalAnchorRef={engagedColumnRef}
              side="right"
            />
          </div>

          {/* The ledger — desktop only; the conversation is the hero on small
              screens. The exit rides under it: "Enter basecamp" once a goal has
              landed, a plain skip before that. */}
          <div className="hidden lg:flex lg:flex-col lg:gap-4">
            <OnboardingLedger goals={{ destinationCaptured, factCaptured }} />
            <button
              type="button"
              onClick={() => void dismiss()}
              disabled={dismissing}
              className="w-full max-w-xs rounded-sm bg-brand px-4 py-3 font-sans text-[11px] uppercase tracking-[0.22em] text-paper shadow-lg transition hover:bg-brand/90 disabled:opacity-40"
            >
              {dismissing
                ? "Closing…"
                : captured
                  ? "Enter basecamp ›"
                  : "Not now ›"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
