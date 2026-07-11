"use client";

// The immersive intake experience — Artemis floating over the landing page's
// dark imagery, gathering the shape of a brand-new adventure.
//
// Session discipline: ONE session, pinned to the traveler's fork, opened
// eagerly with a seeded opener ("Where shall we take you?") and resumed
// idempotently on reload. Every turn carries `surface: "intake"` so the
// backend keeps the agent in the gathering rubric even after the brief lands.
// When the traveler skips — or Artemis calls `complete_intake` — the screen
// docks: imagery fades, the chat card slides to the left column position, and
// we navigate to the trip dashboard where the concierge column resumes the
// SAME session with the whole conversation intact.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";

import {
  createApiClient,
  createSessionEndpoint,
  listTurns,
} from "@ov-black/api-client";

import {
  ConversationPanel,
  type ConversationMessage,
} from "@/app/_components/concierge/ConversationPanel";
import { AgentSurface } from "@/app/_components/concierge/surfaces/AgentSurface";
import { SurfaceContext } from "@/app/_components/concierge/surfaces/SurfaceContext";
import type { OptionView } from "@/app/_components/concierge/surfaces/types";
import {
  optionReply,
  useAgentSurface,
} from "@/app/_components/concierge/surfaces/useAgentSurface";
import { useAgentStream } from "@/lib/agentStream";
import { MOODS, type MoodId } from "@/lib/atmos/moods";
import { createBrowserSupabase } from "@/lib/supabase/client";

import { IntakeBackdrop } from "./IntakeBackdrop";
import {
  IntakeDetailsCard,
  type IntakeDetails,
  type IntakePartyMember,
} from "./IntakeDetailsCard";

const SEEDED_OPENER =
  "Where shall we take you? Tell me what's pulling at you — a place, a " +
  "feeling, a pace — and I'll shape the details as we talk. Whenever " +
  "you're ready to see the journal, just say so.";

export type IntakeExperienceProps = {
  apiBaseUrl: string | null;
  accessToken: string | null;
  clientId: string;
  /** The traveler's fork — the working copy every intake write lands on. */
  itineraryId: string;
  /** The route id the traveler arrived on (the trunk, usually). */
  trunkId: string;
  initial: IntakeDetails;
};

export function IntakeExperience({
  apiBaseUrl,
  accessToken,
  clientId,
  itineraryId,
  trunkId,
  initial,
}: IntakeExperienceProps) {
  const router = useRouter();
  const reduced = useReducedMotion() ?? false;

  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [working, setWorking] = useState(false);
  const [mood, setMood] = useState<MoodId | null>(null);
  const [details, setDetails] = useState<IntakeDetails>(initial);
  const [party, setParty] = useState<IntakePartyMember[]>([]);
  // "immersive" → conversing; "leaving" → dock transition playing, navigation
  // fires on its completion.
  const [phase, setPhase] = useState<"immersive" | "leaving">("immersive");

  const sessionIdRef = useRef<string | null>(null);
  const streamingIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);
  const leavingRef = useRef(false);
  const canChat = Boolean(apiBaseUrl && accessToken && clientId);

  // The drawer beside the chat card — chip-opened place briefs and any
  // agent-pushed panels share one host, exactly like the itinerary/basecamp
  // shells, so a tapped place chip opens the flyout instead of the old popup.
  const chatCardRef = useRef<HTMLDivElement | null>(null);
  const { surface, onSurface, opener, close } = useAgentSurface();

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

  const finishStreaming = useCallback(() => {
    setWorking(false);
    const id = streamingIdRef.current;
    if (id) {
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
      );
    }
    streamingIdRef.current = null;
    setStreaming(false);
  }, []);

  // Skip / move-on both land here: remember the dismissal (session cookie, so
  // the shell's /new redirect never loops in this browser session), then play
  // the dock transition; navigation fires when it completes.
  const leave = useCallback(() => {
    if (leavingRef.current) return;
    leavingRef.current = true;
    for (const id of new Set([itineraryId, trunkId])) {
      document.cookie = `ovb-intake-dismissed-${id}=1; path=/; SameSite=Lax`;
    }
    setPhase("leaving");
  }, [itineraryId, trunkId]);

  const navigateToTrip = useCallback(() => {
    router.push(`/itinerary/${itineraryId}/dashboard`);
  }, [router, itineraryId]);

  const { sendTurn } = useAgentStream({
    getSessionId: () => sessionIdRef.current,
    getAccessToken,
    apiBaseUrl: apiBaseUrl ?? "",
    abortRef,
    extraBody: { surface: "intake" },
    onSurface,
    onActivity: () => {
      if (streamingIdRef.current) setWorking(true);
    },
    onDelta: (frame) => {
      setWorking(false);
      const id = streamingIdRef.current;
      if (id) appendDelta(id, frame.text);
    },
    onDone: finishStreaming,
    onError: () => {
      const id = streamingIdRef.current;
      if (id) {
        appendDelta(
          id,
          "\n\n(The concierge couldn’t respond just now. Try again in a moment.)",
        );
      }
      finishStreaming();
    },
    onMood: (frame) => {
      if (frame.mood_id in MOODS) setMood(frame.mood_id as MoodId);
    },
    onItineraryUpdated: (frame) => {
      const it = frame.itinerary;
      setDetails((prev) => ({
        title: typeof it.title === "string" && it.title ? it.title : prev.title,
        timingKind: it.timing_kind !== undefined ? it.timing_kind : prev.timingKind,
        dateStart: it.date_start !== undefined ? it.date_start : prev.dateStart,
        dateEnd: it.date_end !== undefined ? it.date_end : prev.dateEnd,
        durationNights:
          it.duration_nights !== undefined ? it.duration_nights : prev.durationNights,
        timingNote: it.timing_note !== undefined ? it.timing_note : prev.timingNote,
      }));
    },
    onPartyUpdated: (frame) => {
      setParty((prev) => {
        const rest = prev.filter((m) => m.id !== frame.member.id);
        return [...rest, frame.member];
      });
    },
    // Artemis judged (or was told) that intake is done. Let the parting words
    // finish streaming; the turn's `done` frame follows and `leave` plays the
    // dock transition from there via the pendingLeave flag below.
    onIntakeComplete: () => {
      pendingLeaveRef.current = true;
    },
  });

  // Dock only after the turn that carried `intake_complete` fully streams —
  // the traveler should read Artemis's parting line before the room changes.
  const pendingLeaveRef = useRef(false);
  useEffect(() => {
    if (!streaming && pendingLeaveRef.current) {
      pendingLeaveRef.current = false;
      // A short beat so the last words land before the transition.
      const t = setTimeout(leave, reduced ? 0 : 900);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [streaming, leave, reduced]);

  // Open (or resume — idempotent per scope) the fork-pinned session eagerly
  // with the seeded opener, then replay whatever conversation already exists.
  useEffect(() => {
    if (!canChat || !apiBaseUrl || !accessToken) return;
    let cancelled = false;
    void (async () => {
      const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const opened = await createSessionEndpoint(api, {
        client_id: clientId,
        itinerary_id: itineraryId,
        audience: "traveler",
        seeded_opener: SEEDED_OPENER,
      });
      if (!opened.ok || cancelled) return;
      sessionIdRef.current = opened.session_id;
      const turns = await listTurns(api, opened.session_id);
      if (!turns.ok || cancelled) return;
      const hydrated: ConversationMessage[] = turns.turns
        // A failed turn persists an empty assistant row — replaying it would
        // render a blank bubble, so only real words come back.
        .filter(
          (t) =>
            (t.role === "user" || t.role === "assistant") &&
            t.content.trim().length > 0,
        )
        .map((t) => ({
          id: t.id,
          role: t.role === "user" ? ("user" as const) : ("assistant" as const),
          text: t.content,
        }));
      setMessages(hydrated);
    })();
    return () => {
      cancelled = true;
    };
  }, [canChat, apiBaseUrl, accessToken, clientId, itineraryId]);

  useEffect(() => {
    const ref = abortRef;
    return () => ref.current?.abort();
  }, []);

  const handleSubmit = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !canChat || streaming || phase !== "immersive") return;
      const n = (seqRef.current += 1);
      const userId = `intake-u-${n}`;
      const assistantId = `intake-a-${n}`;
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", text: trimmed },
        { id: assistantId, role: "assistant", text: "", streaming: true },
      ]);
      streamingIdRef.current = assistantId;
      setStreaming(true);
      void sendTurn(trimmed);
    },
    [canChat, streaming, phase, sendTurn],
  );

  // A tapped option answers through the ordinary turn path, phrased as the
  // traveler's own reply — same voice as the other chat shells.
  const onChooseOption = useCallback(
    (option: OptionView) => {
      close();
      handleSubmit(optionReply(option));
    },
    [close, handleSubmit],
  );

  const leaving = phase === "leaving";
  // Any captured shape flips the exit's voice from "skip" to "open the
  // journal" — at that point the traveler isn't abandoning the intake,
  // they're done with it.
  const captured =
    details.title.trim().length > 0 ||
    details.timingKind !== null ||
    party.length > 0;

  return (
    <div
      data-testid="intake-immersive"
      className="relative flex h-dvh flex-col overflow-hidden bg-ink text-paper"
    >
      <motion.div
        animate={{ opacity: leaving ? 0 : 1 }}
        transition={{ duration: reduced ? 0 : 0.9, ease: "easeInOut" }}
        className="absolute inset-0"
      >
        <IntakeBackdrop mood={mood} />
      </motion.div>

      {/* Minimal chrome: the wordmark. The way out lives with the details
          ledger (the one orange note on the screen); below lg — where the
          ledger is hidden — this quiet header link keeps the exit
          reachable. */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <p className="font-sans text-[11px] uppercase tracking-[0.4em] text-paper/80">
          Outdoor Voyage
        </p>
        <button
          type="button"
          data-testid="intake-skip"
          onClick={leave}
          disabled={leaving}
          className="font-sans text-[11px] uppercase tracking-[0.22em] text-paper/60 transition hover:text-paper disabled:opacity-40 lg:hidden"
        >
          Skip for now ›
        </button>
      </header>

      {/* The floating room: headline, chat card center, details beside it. */}
      <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center px-4 pb-6 sm:px-10">
        <motion.div
          animate={{ opacity: leaving ? 0 : 1, y: leaving ? -12 : 0 }}
          transition={{ duration: reduced ? 0 : 0.5 }}
          className="w-full max-w-5xl pb-6 pt-2 text-center lg:text-left"
        >
          <p className="font-sans text-[11px] uppercase tracking-[0.3em] text-paper/55">
            A new adventure
          </p>
          <h1 className="mt-2 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
            Where shall we take you?
          </h1>
        </motion.div>

        <div className="flex min-h-0 w-full max-w-5xl flex-1 items-stretch justify-center gap-8 lg:justify-start">
          {/* The chat card. On leave it slides toward the left column where
              the concierge normally docks, while everything else fades. */}
          <motion.div
            ref={chatCardRef}
            data-testid="intake-chat"
            layout
            animate={
              leaving
                ? { x: reduced ? 0 : -48, opacity: 0 }
                : { x: 0, opacity: 1 }
            }
            transition={{ duration: reduced ? 0 : 0.7, ease: "easeInOut" }}
            onAnimationComplete={() => {
              if (leaving) navigateToTrip();
            }}
            className="flex min-h-0 w-full max-w-xl flex-col overflow-hidden rounded-lg border border-paper/10 bg-paper text-ink shadow-2xl"
          >
            <SurfaceContext.Provider value={opener}>
              <ConversationPanel
                messages={messages}
                onSubmit={handleSubmit}
                disabled={!canChat || leaving}
                sending={streaming}
                hideHeader
                working={working}
                placeholder="Tell Artemis what you're dreaming of…"
              />
            </SurfaceContext.Provider>
          </motion.div>

          {/* The details ledger — desktop only; the conversation is the
              hero on small screens. The exit rides under it: "Open the
              journal" once the adventure has any shape, a plain skip
              before that. */}
          <motion.div
            animate={{ opacity: leaving ? 0 : 1 }}
            transition={{ duration: reduced ? 0 : 0.5 }}
            className="hidden lg:flex lg:flex-col lg:gap-4"
          >
            <IntakeDetailsCard details={details} party={party} />
            <button
              type="button"
              data-testid="intake-open-journal"
              onClick={leave}
              disabled={leaving}
              className="w-full max-w-xs rounded-sm bg-brand px-4 py-3 font-sans text-[11px] uppercase tracking-[0.22em] text-paper shadow-lg transition hover:bg-brand/90 disabled:opacity-40"
            >
              {captured ? "Open the journal ›" : "Skip for now ›"}
            </button>
          </motion.div>
        </div>
      </div>

      {/* The place-brief flyout — emerges from the chat card's left edge, over
          the immersive backdrop, so it never covers the details ledger beside
          it on the right. */}
      <AgentSurface
        surface={surface}
        busy={streaming}
        onClose={close}
        onChooseOption={onChooseOption}
        anchorRef={chatCardRef}
        side="left"
      />
    </div>
  );
}
