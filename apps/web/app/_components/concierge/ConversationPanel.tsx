"use client";

// The one concierge conversation surface, shared by every chat window so the
// advisor's trip-view concierge and the traveler's basecamp rail look and behave
// the same (M006/PS7 finish: unify the message rendering, not just the chrome).
//
// It renders the canonical "bubble" look lifted from the itinerary ChatPanel —
// ink user bubbles on the right, paper assistant bubbles on the left, an inline
// proposed-card stub, and a single-line composer. Callers normalise their own
// turn model into `ConversationMessage[]`; itinerary-specific extras (proposed
// cards, "show on timeline") are optional, so a surface with none just omits
// them.

import type { NodeResponse } from "@ov-black/api-client";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { MapCompassIndicator } from "@/app/_components/MapCompassIndicator";
import {
  CardBody,
  inferCardKind,
} from "@/app/_components/itinerary-graph/shared/cards/CardBody";
import { CardShell } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { CRAFTED_FALLBACK_COPY } from "@/app/chat/[client_id]/_components/ConversationStream";
import { OnboardingMilestoneCard } from "@/app/chat/[client_id]/_components/OnboardingMilestoneCard";
import { ProseMessage } from "@/app/chat/[client_id]/_components/ProseMessage";
import { AutoGrowTextarea } from "@/components/ui/auto-grow-textarea";
import { ScrollControls } from "@/components/ui/scroll-controls";
import { useSentHistory } from "@/lib/useSentHistory";

// A single conversation row. `role` is the union across every surface: the
// itinerary concierge only ever produces user/assistant/system; basecamp adds
// the client-synthesized `milestone` card and the `error` fallback row. `tool`
// rows are agent plumbing — rendered quietly, kept in the DOM for parity.
export type ConversationRole =
  "user" | "assistant" | "system" | "tool" | "error" | "milestone";

export type ConversationMessage = {
  id: string;
  role: ConversationRole;
  text: string;
  streaming?: boolean;
};

// A proposed graph node awaiting accept/dismiss. A structural subset of the
// itinerary NodeResponse, so the itinerary surface passes its rows straight in;
// surfaces without proposals omit the prop. `metadata` is the node's card-attrs
// dict (present on real graph proposals) — it lets a typed proposal (a flight)
// render as its own card instead of a bare title.
export type ConversationProposal = {
  id: string;
  type: string;
  title: string;
  metadata?: { [key: string]: unknown };
};

export interface ConversationPanelProps {
  messages: ConversationMessage[];
  onSubmit: (text: string) => void;
  proposals?: ConversationProposal[];
  onAccept?: (id: string) => void;
  onDismiss?: (id: string) => void;
  onScrollToNode?: (id: string) => void;
  // Fully inert: no chat context (missing token/client). The input is disabled
  // and nothing can be sent.
  disabled?: boolean;
  // A turn is streaming. Blocks a new submit and dims Send, but keeps the input
  // ENABLED so it never loses focus. A `disabled` input is blurred by the
  // browser the instant a turn starts and never regains focus on re-enable —
  // which is why the composer used to drop focus after every message.
  sending?: boolean;
  // Hide the panel's own "Concierge" header — used when a host already provides
  // one (the mobile bottom sheet's drag handle, or basecamp's people-circles).
  hideHeader?: boolean;
  // Composer placeholder — differs per surface ("Ask me to propose…" for the
  // advisor, "Write to your concierge" for the traveler).
  placeholder?: string;
  // The concierge is off calling tools (anonymous `activity` pulse) — the
  // streaming bubble shows the map-fold indicator instead of the text caret.
  working?: boolean;
}

export function ConversationPanel({
  messages,
  onSubmit,
  proposals = [],
  onAccept,
  onDismiss,
  onScrollToNode,
  disabled = false,
  sending = false,
  hideHeader = false,
  placeholder = "Ask me to propose, assemble, or swap…",
  working = false,
}: ConversationPanelProps) {
  const [text, setText] = useState("");
  const history = useSentHistory(setText);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, proposals.length]);

  const submitText = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled || sending) return;
    onSubmit(trimmed);
    history.record(trimmed);
    setText("");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submitText();
  };

  return (
    <div
      data-testid="conversation-panel"
      className="relative z-20 flex h-full min-h-0 flex-col bg-paper/80 backdrop-blur-md"
    >
      {hideHeader ? null : (
        <div className="border-b border-ink/10 px-4 py-2.5">
          <div className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
            Concierge
          </div>
          <div className="font-serif text-lg text-ink">Conversation</div>
        </div>
      )}
      {/* Relative viewport wrapper so the scroll jump-buttons pin to the scroll
          area (not the composer below). min-h-0 lets it shrink below its content
          so overflow-y-auto actually scrolls, instead of growing past the panel. */}
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 bg-white"
        >
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} working={working} />
            ))}
            {proposals.map((p) => {
              // Render the proposal as the SAME card the timeline / Collection
              // show (M006 harmonization): the shared CardShell substrate +
              // type-specific CardBody, with the accept/dismiss row riding in
              // the shell's `actions` slot — not a bespoke stub.
              const node = nodeFromProposal(p);
              const kind = inferCardKind(node);
              return (
                <motion.div
                  key={`inline-${p.id}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                >
                  <CardShell
                    kind={kind}
                    status="pending"
                    width="glance"
                    {...(onScrollToNode
                      ? {
                          headerExtra: (
                            <button
                              type="button"
                              onClick={() => onScrollToNode(p.id)}
                              title="Show on timeline"
                              aria-label="Show on timeline"
                              className="rounded-md border border-ink/15 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/65 hover:border-ink/40 hover:text-ink"
                            >
                              Show ↗
                            </button>
                          ),
                        }
                      : {})}
                    actions={
                      <ProposalActions
                        onAccept={() => onAccept?.(p.id)}
                        onDismiss={() => onDismiss?.(p.id)}
                      />
                    }
                  >
                    <CardBody node={node} kind={kind} tzOffsetHours={0} />
                  </CardShell>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
        <ScrollControls targetRef={scrollRef} />
      </div>
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-2 border-t border-ink/10 px-3 py-2"
      >
        <AutoGrowTextarea
          className="min-w-0 flex-1 rounded-md border border-ink/15 bg-paper-white px-3 py-2 text-[13px] outline-hidden focus:border-ink/40"
          maxHeightPx={160}
          placeholder={placeholder}
          value={text}
          onValueChange={history.onValueChange}
          onKeyDown={history.onKeyDown}
          onSubmit={submitText}
          disabled={disabled}
        />
        <button
          type="submit"
          disabled={disabled || sending || text.trim().length === 0}
          className="rounded-md bg-ink px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-paper disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}

// ── Proposed-node card ────────────────────────────────────────────────────────
// Adapt a proposal (a structural subset of NodeResponse) into the full node
// shape CardBody reads, so the concierge's proposals render as the SAME card the
// timeline and Collection show — a flight boarding pass, a hotel tile, etc. A
// proposal is by definition still pending, so status is fixed; source/source_id
// aren't read by any CardBody variant, so they're nulled.
function nodeFromProposal(p: ConversationProposal): NodeResponse {
  return {
    id: p.id,
    itinerary_id: "",
    parent_subgraph_id: null,
    type: p.type as NodeResponse["type"],
    status: "pending",
    title: p.title,
    source: null,
    source_id: null,
    metadata: p.metadata ?? {},
  };
}

// The accept/dismiss row, rendered in the CardShell `actions` slot — same
// footprint as the mood board's Must Do / Not This Time row so a proposed card
// closes with an action band, not a bare edge.
function ProposalActions({
  onAccept,
  onDismiss,
}: {
  onAccept: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 px-3 pb-3 pt-3">
      <button
        type="button"
        onClick={onAccept}
        className="h-9 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.18em] text-ink transition-colors hover:bg-ink/5"
      >
        Accept
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="h-9 rounded-md border border-ink/15 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/60 transition-colors hover:bg-ink/5"
      >
        Dismiss
      </button>
    </div>
  );
}

// The "still streaming" placeholder shown between token deltas (or before the
// first one lands): three ink dots gently rising and fading in sequence, in
// place of the old blunt caret rectangle. `withText` bumps it onto its own line
// once some reply text has arrived so it reads as a continuation, not a caret.
function TypingDots({ withText }: { withText: boolean }) {
  return (
    <span
      role="status"
      aria-label="Concierge is typing…"
      className={[
        "items-center gap-1 align-middle",
        withText ? "mt-1 flex" : "inline-flex",
      ].join(" ")}
    >
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="inline-block h-[5px] w-[5px] rounded-full bg-current opacity-60"
          animate={{ y: [0, -3, 0], opacity: [0.3, 0.85, 0.3] }}
          transition={{
            duration: 1.1,
            repeat: Infinity,
            ease: "easeInOut",
            delay: i * 0.18,
          }}
        />
      ))}
    </span>
  );
}

function MessageBubble({
  message,
  working = false,
}: {
  message: ConversationMessage;
  working?: boolean;
}) {
  // The client-synthesized onboarding celebration — a card, not a bubble.
  if (message.role === "milestone") {
    return <OnboardingMilestoneCard />;
  }

  // The D015 fallback row: render the crafted copy, never the raw reason code.
  if (message.role === "error") {
    return (
      <div
        data-role="error"
        className="font-sans text-[12px] leading-relaxed text-ink/70"
      >
        {CRAFTED_FALLBACK_COPY}
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="rounded-md border border-dashed border-ink/15 bg-paper/60 px-3 py-2 text-[11px] italic text-ink/60">
        {message.text}
      </div>
    );
  }

  // `tool` rows are agent plumbing — kept quiet, mirroring the craft shell.
  if (message.role === "tool") {
    return (
      <div className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/40">
        {message.text}
      </div>
    );
  }

  const isUser = message.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      data-role={message.role}
      data-streaming={message.streaming ? "true" : undefined}
      className={[
        "max-w-[86%] rounded-lg px-3 py-2 text-[16px] leading-relaxed",
        isUser ? "ml-auto bg-ink text-paper" : "bg-ink/5 text-ink",
      ].join(" ")}
    >
      {/* User bubbles stay literal (they typed it); the concierge's replies
          render as markdown + embeds. */}
      {isUser ? message.text : <ProseMessage content={message.text} />}
      {message.streaming ? (
        working ? (
          <span className={message.text ? "mt-1 block" : "block"}>
            <MapCompassIndicator />
          </span>
        ) : (
          <TypingDots withText={Boolean(message.text)} />
        )
      ) : null}
    </motion.div>
  );
}
