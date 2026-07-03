"use client";

// Renders the conversation column. Each turn row carries data-turn-id and
// data-role so the acceptance suite (and human debugging via DevTools) can
// assert on DOM state without poking React internals. Agent turns use the
// Cormorant serif; user turns and the D015 error row use Inter sans. The
// error row renders the literal fallback copy from D015 — the copy string
// is load-bearing and must match the sign-in flow's "auth_upstream_unavailable"
// message verbatim so the whole product speaks in one voice when things
// break.

import { useEffect, useRef } from "react";

import { OnboardingMilestoneCard } from "./OnboardingMilestoneCard";
import { ProseMessage } from "./ProseMessage";
import type { AgentTurnView, StreamState } from "./types";

export const CRAFTED_FALLBACK_COPY =
  "Our concierge is stepping away for a moment. Please try again.";

const AUTO_SCROLL_THRESHOLD_PX = 40;

export type ConversationStreamProps = {
  turns: AgentTurnView[];
  streaming: StreamState | null;
};

export function ConversationStream({
  turns,
  streaming,
}: ConversationStreamProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Remember whether the user was already pinned to the bottom BEFORE the
  // incoming update landed — we must only auto-scroll when they hadn't
  // scrolled up to re-read, otherwise we yank their view.
  const wasAtBottomRef = useRef(true);

  // Snapshot scroll position before each render so the post-render effect
  // below can decide whether to glue to the bottom.
  const el = scrollRef.current;
  if (el) {
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    wasAtBottomRef.current = distanceFromBottom <= AUTO_SCROLL_THRESHOLD_PX;
  }

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    if (wasAtBottomRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [turns, streaming?.buffer]);

  return (
    <section
      id="conversation"
      ref={scrollRef}
      className="relative overflow-y-auto bg-paper text-ink"
      data-testid="conversation-stream"
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-8 px-8 py-12">
        {turns.map((turn) => (
          <TurnRow key={turn.id} turn={turn} />
        ))}
        {streaming ? (
          <div
            data-testid="streaming-turn"
            data-role="assistant"
            data-turn-index={streaming.turnIndex}
            className="font-serif text-[21px] leading-relaxed text-ink"
          >
            {streaming.buffer.trim() ? (
              <ProseMessage content={streaming.buffer} />
            ) : (
              "\u00a0"
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function TurnRow({ turn }: { turn: AgentTurnView }) {
  if (turn.role === "milestone") {
    return <OnboardingMilestoneCard />;
  }

  if (turn.role === "error") {
    return (
      <div
        data-turn-id={turn.id}
        data-role="error"
        className="font-sans text-sm leading-relaxed text-ink/70"
      >
        {CRAFTED_FALLBACK_COPY}
      </div>
    );
  }

  if (turn.role === "assistant") {
    return (
      <div
        data-turn-id={turn.id}
        data-role="assistant"
        className="font-serif text-[21px] leading-relaxed text-ink"
      >
        <ProseMessage content={turn.content} />
      </div>
    );
  }

  if (turn.role === "user") {
    return (
      <div
        data-turn-id={turn.id}
        data-role="user"
        className="self-end rounded-md bg-ink/5 px-4 py-3 font-sans text-base leading-relaxed text-ink"
      >
        {turn.content}
      </div>
    );
  }

  // system / tool roles aren't rendered in the craft shell (they're agent
  // plumbing, not conversation). We still expose them in the DOM for tests
  // but keep them visually quiet.
  return (
    <div
      data-turn-id={turn.id}
      data-role={turn.role}
      className="font-sans text-xs uppercase tracking-[0.2em] text-ink/40"
    >
      {turn.content}
    </div>
  );
}
